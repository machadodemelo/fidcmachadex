from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

import pandas as pd

from services.variaveis_fnet import VARIAVEIS_FNET, competencia_columns, resolve_tag_path, variaveis_fnet_df


DEFAULT_OVERRIDES_DIR = Path("manual_overrides")
MONEY_SCALE = 1_000_000.0


@dataclass(frozen=True)
class MonitoringTables:
    raw_variables_df: pd.DataFrame
    indicators_df: pd.DataFrame
    aging_df: pd.DataFrame
    audit_df: pd.DataFrame


def read_wide_csv(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    return normalize_wide_frame(frame)


def normalize_wide_frame(wide_df: pd.DataFrame) -> pd.DataFrame:
    frame = wide_df.copy()
    if "tag_path" not in frame.columns:
        frame = frame.reset_index()
        if "tag_path" not in frame.columns:
            first_col = frame.columns[0]
            frame = frame.rename(columns={first_col: "tag_path"})
    frame["tag_path"] = frame["tag_path"].astype(str)
    return frame.set_index("tag_path", drop=False)


def load_manual_overrides(cnpj: str, *, overrides_dir: Path | None = None) -> dict[str, Any]:
    path = _override_path(cnpj, overrides_dir=overrides_dir)
    if not path.exists():
        return {"cnpj": _normalize_cnpj(cnpj), "competencias": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cnpj": _normalize_cnpj(cnpj), "competencias": {}}
    competencias = payload.get("competencias") if isinstance(payload, dict) else {}
    return {
        "cnpj": _normalize_cnpj(str(payload.get("cnpj") if isinstance(payload, dict) else cnpj) or cnpj),
        "competencias": competencias if isinstance(competencias, dict) else {},
    }


def save_manual_overrides(
    cnpj: str,
    payload: dict[str, Any],
    *,
    overrides_dir: Path | None = None,
) -> Path:
    path = _override_path(cnpj, overrides_dir=overrides_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {"cnpj": _normalize_cnpj(cnpj), "competencias": {}}
    for competencia, values in (payload.get("competencias") or {}).items():
        if not isinstance(values, dict):
            continue
        row = {}
        for key in ("vl_total_mz", "rent_mz"):
            parsed = _to_float(values.get(key))
            if parsed is not None:
                row[key] = parsed
        if row:
            normalized["competencias"][str(competencia)] = row
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_monitoring_tables(
    wide_df: pd.DataFrame,
    competencias: list[str] | None = None,
    *,
    cnpj: str = "",
    overrides: dict[str, Any] | None = None,
    dashboard_data: Any | None = None,
) -> MonitoringTables:
    wide_lookup = normalize_wide_frame(wide_df)
    resolved_competencias = competencias or competencia_columns(wide_lookup)
    raw_variables_df = build_raw_variables_df(wide_lookup, resolved_competencias)
    indicators_df, audit_df = build_indicators_df(
        wide_lookup,
        resolved_competencias,
        cnpj=cnpj,
        overrides=overrides,
        dashboard_data=dashboard_data,
    )
    aging_df = build_aging_df(wide_lookup, resolved_competencias, dashboard_data=dashboard_data)
    return MonitoringTables(
        raw_variables_df=raw_variables_df,
        indicators_df=indicators_df,
        aging_df=aging_df,
        audit_df=audit_df,
    )


def build_raw_variables_df(wide_df: pd.DataFrame, competencias: list[str]) -> pd.DataFrame:
    wide_lookup = normalize_wide_frame(wide_df)
    catalog = variaveis_fnet_df(wide_lookup)
    rows: list[dict[str, object]] = []
    for item in catalog.itertuples(index=False):
        tag_path = getattr(item, "tag_path")
        values = _series_for_path(wide_lookup, competencias, tag_path)
        row = {
            "id_cvm": item.id_cvm,
            "label": item.label,
            "secao": item.secao,
            "tag_path": tag_path or "",
            "status": "OK" if tag_path else "AUSENTE",
        }
        row.update({competencia: values.loc[competencia] for competencia in competencias})
        rows.append(row)
    return pd.DataFrame(rows)


def build_indicators_df(
    wide_df: pd.DataFrame,
    competencias: list[str],
    *,
    cnpj: str = "",
    overrides: dict[str, Any] | None = None,
    dashboard_data: Any | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    wide_lookup = normalize_wide_frame(wide_df)
    overrides = overrides or load_manual_overrides(cnpj)

    pl_raw_fallback = _series(wide_lookup, competencias, "PATRLIQ/VL_SOM_PATRLIQ")
    dircred_raw_fallback = _sum_series(
        wide_lookup,
        competencias,
        ["CRED_EXISTE/VL_SOM_DICRED_AQUIS", "DICRED/VL_DICRED"],
    )
    venc_ate_90_raw_fallback = _sum_series(wide_lookup, competencias, _aging_ids(["VL_INAD_VENC_30", "VL_INAD_VENC_31_60", "VL_INAD_VENC_61_90"]))
    venc_acima_90_raw_fallback = _sum_series(
        wide_lookup,
        competencias,
        _aging_ids(
            [
                "VL_INAD_VENC_91_120",
                "VL_INAD_VENC_121_150",
                "VL_INAD_VENC_151_180",
                "VL_INAD_VENC_181_360",
                "VL_INAD_VENC_361_720",
                "VL_INAD_VENC_721_1080",
                "VL_INAD_VENC_1080",
            ]
        ),
    )
    venc_over_30_raw_fallback = _sum_series(
        wide_lookup,
        competencias,
        _aging_ids(
            [
                "VL_INAD_VENC_31_60",
                "VL_INAD_VENC_61_90",
                "VL_INAD_VENC_91_120",
                "VL_INAD_VENC_121_150",
                "VL_INAD_VENC_151_180",
                "VL_INAD_VENC_181_360",
                "VL_INAD_VENC_361_720",
                "VL_INAD_VENC_721_1080",
                "VL_INAD_VENC_1080",
            ]
        ),
    )
    venc_over_60_raw_fallback = _sum_series(
        wide_lookup,
        competencias,
        _aging_ids(
            [
                "VL_INAD_VENC_61_90",
                "VL_INAD_VENC_91_120",
                "VL_INAD_VENC_121_150",
                "VL_INAD_VENC_151_180",
                "VL_INAD_VENC_181_360",
                "VL_INAD_VENC_361_720",
                "VL_INAD_VENC_721_1080",
                "VL_INAD_VENC_1080",
            ]
        ),
    )
    venc_over_180_raw_fallback = _sum_series(
        wide_lookup,
        competencias,
        _aging_ids(["VL_INAD_VENC_181_360", "VL_INAD_VENC_361_720", "VL_INAD_VENC_721_1080", "VL_INAD_VENC_1080"]),
    )
    venc_over_360_raw_fallback = _sum_series(
        wide_lookup,
        competencias,
        _aging_ids(["VL_INAD_VENC_361_720", "VL_INAD_VENC_721_1080", "VL_INAD_VENC_1080"]),
    )
    venc_total_raw_fallback = _sum_existing_series([venc_ate_90_raw_fallback, venc_acima_90_raw_fallback])
    pdd_raw_fallback = _sum_series(
        wide_lookup,
        competencias,
        ["CRED_EXISTE/VL_PROVIS_REDUC_RECUP", "DICRED/VL_DICRED_PROVIS_REDUC_RECUP"],
    )
    recomp_raw = _series(wide_lookup, competencias, "DICRED_MES_ALIEN_RECOMP/VL_DICRED_ALIEN")
    sr_raw_fallback = _series(wide_lookup, competencias, "CLASSE_SENIOR/VL_TOTAL")
    sub_raw_fallback = _series(wide_lookup, competencias, "CLASSE_SUBORD/VL_TOTAL")
    rent_sr_fallback = _series(wide_lookup, competencias, "RENT_CLASSE_SENIOR/PR_APURADA")
    rent_sub_fallback = _series(wide_lookup, competencias, "RENT_CLASSE_SUBORD/PR_APURADA")
    mz_raw_override = _override_series(overrides, competencias, "vl_total_mz")
    rent_mz_override = _override_series(overrides, competencias, "rent_mz")

    pl_raw = _coalesce_series(
        _dashboard_series(dashboard_data, "subordination_history_df", competencias, "pl_total"),
        pl_raw_fallback,
    )
    dircred_raw = _coalesce_series(
        _dashboard_series(dashboard_data, "dc_canonical_history_df", competencias, "dc_total_canonico"),
        dircred_raw_fallback,
    )
    pdd_raw = _coalesce_series(
        _dashboard_series(dashboard_data, "default_history_df", competencias, "provisao_total"),
        pdd_raw_fallback,
    )
    venc_total_raw = _coalesce_series(
        _dashboard_series(dashboard_data, "default_history_df", competencias, "inadimplencia_total"),
        venc_total_raw_fallback,
    )
    venc_over_30_raw = _coalesce_series(
        _dashboard_over_series(dashboard_data, competencias, "Over 30"),
        venc_over_30_raw_fallback,
    )
    venc_over_60_raw = _coalesce_series(
        _dashboard_over_series(dashboard_data, competencias, "Over 60"),
        venc_over_60_raw_fallback,
    )
    venc_acima_90_raw = _coalesce_series(
        _dashboard_over_series(dashboard_data, competencias, "Over 90"),
        venc_acima_90_raw_fallback,
    )
    venc_over_180_raw = _coalesce_series(
        _dashboard_over_series(dashboard_data, competencias, "Over 180"),
        venc_over_180_raw_fallback,
    )
    venc_over_360_raw = _coalesce_series(
        _dashboard_over_series(dashboard_data, competencias, "Over 360"),
        venc_over_360_raw_fallback,
    )
    venc_ate_90_raw = _coalesce_series(
        _subtract_nonnegative(venc_total_raw, venc_acima_90_raw),
        venc_ate_90_raw_fallback,
    )
    sr_raw = _coalesce_series(
        _dashboard_series(dashboard_data, "subordination_history_df", competencias, "pl_senior"),
        sr_raw_fallback,
    )
    mz_raw = _coalesce_series(
        _dashboard_series(dashboard_data, "subordination_history_df", competencias, "pl_mezzanino"),
        mz_raw_override,
    )
    sub_raw = _coalesce_series(
        _dashboard_series(dashboard_data, "subordination_history_df", competencias, "pl_subordinada_strict"),
        sub_raw_fallback,
    )
    rent_sr = _coalesce_series(
        _dashboard_weighted_return_series(dashboard_data, competencias, "senior"),
        rent_sr_fallback,
    )
    rent_mz = _coalesce_series(
        _dashboard_weighted_return_series(dashboard_data, competencias, "mezzanino"),
        rent_mz_override,
    )
    rent_sub = _coalesce_series(
        _dashboard_weighted_return_series(dashboard_data, competencias, "subordinada"),
        rent_sub_fallback,
    )

    canonical_suffix = " (fonte canônica da Visão Executiva quando disponível)"

    specs: list[tuple[str, str, pd.Series, str, str]] = [
        ("PL (R$)", "R$ bruto", pl_raw, "PL canônico; fallback PATRLIQ/VL_SOM_PATRLIQ", f"subordination_history_df.pl_total; PATRLIQ/VL_SOM_PATRLIQ{canonical_suffix}"),
        ("PL (R$ MM)", "R$ MM", pl_raw / MONEY_SCALE, "PL canônico ÷ 1e6", f"subordination_history_df.pl_total; PATRLIQ/VL_SOM_PATRLIQ{canonical_suffix}"),
        ("Dir Cred (R$ MM)", "R$ MM", dircred_raw / MONEY_SCALE, "Direitos creditórios canônicos ÷ 1e6", f"dc_canonical_history_df.dc_total_canonico; fallback CRED_EXISTE/DICRED{canonical_suffix}"),
        ("Dir Cred / PL", "ratio", _safe_divide(dircred_raw, pl_raw), "Dir Cred ÷ PL", "derivado"),
        ("Vencidos <= 90 d (R$ MM)", "R$ MM", venc_ate_90_raw / MONEY_SCALE, "Vencidos totais canônicos - Over 90d", f"default_history_df.inadimplencia_total - default_over_history_df.Over90{canonical_suffix}"),
        ("Vencidos > 90 d (R$ MM)", "R$ MM", venc_acima_90_raw / MONEY_SCALE, "Over 90d canônico ÷ 1e6", f"default_over_history_df.Over90.valor{canonical_suffix}"),
        ("Vencidos Total (R$ MM)", "R$ MM", venc_total_raw / MONEY_SCALE, "Vencidos <=90d + Vencidos >90d", "derivado"),
        ("Vencidos <= 90 d / Crédito", "ratio", _safe_divide(venc_ate_90_raw, dircred_raw), "Vencidos <=90d ÷ Dir Cred", "derivado"),
        ("Vencidos > 90 d / Crédito", "ratio", _safe_divide(venc_acima_90_raw, dircred_raw), "Vencidos >90d ÷ Dir Cred", "derivado"),
        ("Vencidos Total / Crédito", "ratio", _safe_divide(venc_total_raw, dircred_raw), "Vencidos Total ÷ Dir Cred", "derivado"),
        ("Vencidos Over 30 d (R$ MM)", "R$ MM", venc_over_30_raw / MONEY_SCALE, "Over 30d canônico ÷ 1e6", f"default_over_history_df.Over30.valor{canonical_suffix}"),
        ("Vencidos Over 30 d / Crédito", "ratio", _safe_divide(venc_over_30_raw, dircred_raw), "Vencidos Over 30d ÷ Dir Cred", "derivado"),
        ("Vencidos Over 60 d (R$ MM)", "R$ MM", venc_over_60_raw / MONEY_SCALE, "Over 60d canônico ÷ 1e6", f"default_over_history_df.Over60.valor{canonical_suffix}"),
        ("Vencidos Over 60 d / Crédito", "ratio", _safe_divide(venc_over_60_raw, dircred_raw), "Vencidos Over 60d ÷ Dir Cred", "derivado"),
        ("Vencidos Over 90 d (R$ MM)", "R$ MM", venc_acima_90_raw / MONEY_SCALE, "Over 90d canônico ÷ 1e6", f"default_over_history_df.Over90.valor{canonical_suffix}"),
        ("Vencidos Over 90 d / Crédito", "ratio", _safe_divide(venc_acima_90_raw, dircred_raw), "Vencidos Over 90d ÷ Dir Cred", "derivado"),
        ("Vencidos Over 180 d (R$ MM)", "R$ MM", venc_over_180_raw / MONEY_SCALE, "Over 180d canônico ÷ 1e6", f"default_over_history_df.Over180.valor{canonical_suffix}"),
        ("Vencidos Over 180 d / Crédito", "ratio", _safe_divide(venc_over_180_raw, dircred_raw), "Vencidos Over 180d ÷ Dir Cred", "derivado"),
        ("Vencidos Over 360 d (R$ MM)", "R$ MM", venc_over_360_raw / MONEY_SCALE, "Over 360d canônico ÷ 1e6", f"default_over_history_df.Over360.valor{canonical_suffix}"),
        ("Vencidos Over 360 d / Crédito", "ratio", _safe_divide(venc_over_360_raw, dircred_raw), "Vencidos Over 360d ÷ Dir Cred", "derivado"),
        ("PDD (R$ MM)", "R$ MM", pdd_raw / MONEY_SCALE, "PDD canônica ÷ 1e6", f"default_history_df.provisao_total; fallback PDD aquisição/sem aquisição{canonical_suffix}"),
        ("PDD / Crédito", "ratio", _safe_divide(pdd_raw, dircred_raw), "PDD ÷ Dir Cred", "derivado"),
        ("PDD / Venc > 90 d", "ratio", _safe_divide(pdd_raw, venc_acima_90_raw), "PDD ÷ Vencidos >90d", "derivado"),
        ("PDD / Venc Total", "ratio", _safe_divide(pdd_raw, venc_total_raw), "PDD ÷ Vencidos Total", "derivado"),
        ("Recompras (R$ MM)", "R$ MM", recomp_raw / MONEY_SCALE, "DICRED_MES_ALIEN_RECOMP/VL_DICRED_ALIEN ÷ 1e6", "DICRED_MES_ALIEN_RECOMP/VL_DICRED_ALIEN"),
        ("Recompras / Crédito", "ratio", _safe_divide(recomp_raw, dircred_raw), "Recompras ÷ Dir Cred", "derivado"),
        ("Recompras / PL", "ratio", _safe_divide(recomp_raw, pl_raw), "Recompras ÷ PL", "derivado"),
        ("Cotas SR / PL %", "%", _safe_divide(sr_raw, pl_raw) * 100.0, "PL sênior canônico ÷ PL", f"subordination_history_df.pl_senior; fallback CLASSE_SENIOR/VL_TOTAL{canonical_suffix}"),
        ("Cotas Sub / PL %", "%", _safe_divide(sub_raw, pl_raw) * 100.0, "PL subordinado estrito canônico ÷ PL", f"subordination_history_df.pl_subordinada_strict; fallback CLASSE_SUBORD/VL_TOTAL{canonical_suffix}"),
        ("Rentabilidade SR % a.m.", "%", rent_sr, "Média ponderada por PL das séries sênior", f"return_history_df ponderado por quota_pl_history_df{canonical_suffix}"),
        ("Rentabilidade Sub % a.m.", "%", rent_sub, "Média ponderada por PL das séries subordinadas", f"return_history_df ponderado por quota_pl_history_df{canonical_suffix}"),
    ]
    if not mz_raw.isna().all():
        specs.append(("Cotas MZ / PL %", "%", _safe_divide(mz_raw, pl_raw) * 100.0, "PL mezanino canônico ou override ÷ PL", f"subordination_history_df.pl_mezzanino; manual_overrides{canonical_suffix}"))
    if not rent_mz.isna().all():
        specs.append(("Rentabilidade MZ % a.m.", "%", rent_mz, "Média ponderada por PL das séries mezanino ou override", f"return_history_df ponderado por quota_pl_history_df; manual_overrides{canonical_suffix}"))

    rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    for ordem, (indicador, unidade, values, formula, fonte) in enumerate(specs, start=1):
        row: dict[str, object] = {"ordem": ordem, "indicador": indicador, "unidade": unidade}
        row.update({competencia: _to_nullable(values.loc[competencia]) for competencia in competencias})
        rows.append(row)
        audit_rows.append(
            {
                "indicador": indicador,
                "formula": formula,
                "fonte": fonte,
                "status": "OK" if not values.isna().all() else "AUSENTE",
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(audit_rows)


def build_aging_df(wide_df: pd.DataFrame, competencias: list[str], *, dashboard_data: Any | None = None) -> pd.DataFrame:
    wide_lookup = normalize_wide_frame(wide_df)
    dircred_raw = _coalesce_series(
        _dashboard_series(dashboard_data, "dc_canonical_history_df", competencias, "dc_total_canonico"),
        _sum_series(wide_lookup, competencias, ["CRED_EXISTE/VL_SOM_DICRED_AQUIS", "DICRED/VL_DICRED"]),
    )
    buckets = [
        ("1-30d", ["VL_INAD_VENC_30"], ["Até 30 dias"]),
        ("31-60d", ["VL_INAD_VENC_31_60"], ["31 a 60 dias"]),
        ("61-90d", ["VL_INAD_VENC_61_90"], ["61 a 90 dias"]),
        ("91-120d", ["VL_INAD_VENC_91_120"], ["91 a 120 dias"]),
        ("121-150d", ["VL_INAD_VENC_121_150"], ["121 a 150 dias"]),
        ("151-180d", ["VL_INAD_VENC_151_180"], ["151 a 180 dias"]),
        ("181-360d", ["VL_INAD_VENC_181_360"], ["181 a 360 dias"]),
        ("361d+", ["VL_INAD_VENC_361_720", "VL_INAD_VENC_721_1080", "VL_INAD_VENC_1080"], ["361 a 720 dias", "721 a 1080 dias", "Acima de 1080 dias"]),
    ]
    rows = []
    cumulative = pd.Series([0.0] * len(competencias), index=competencias, dtype="Float64")
    for ordem, (bucket, suffixes, dashboard_labels) in enumerate(buckets, start=1):
        raw = _coalesce_series(
            _dashboard_aging_bucket_series(dashboard_data, competencias, dashboard_labels),
            _sum_series(wide_lookup, competencias, _aging_ids(suffixes)),
        )
        cumulative = _sum_existing_series([cumulative, raw])
        row = {"ordem": ordem, "bucket": bucket, "unidade": "R$ MM"}
        row.update({competencia: _to_nullable((raw / MONEY_SCALE).loc[competencia]) for competencia in competencias})
        rows.append(row)
        ratio_row = {"ordem": ordem + 100, "bucket": f"{bucket} acumulado / Crédito", "unidade": "ratio"}
        cumulative_ratio = _safe_divide(cumulative, dircred_raw)
        ratio_row.update({competencia: _to_nullable(cumulative_ratio.loc[competencia]) for competencia in competencias})
        rows.append(ratio_row)
    return pd.DataFrame(rows)


def _series(wide_lookup: pd.DataFrame, competencias: list[str], short_id: str) -> pd.Series:
    tag_path = resolve_tag_path(short_id, wide_lookup)
    return _series_for_path(wide_lookup, competencias, tag_path)


def _series_for_path(wide_lookup: pd.DataFrame, competencias: list[str], tag_path: str | None) -> pd.Series:
    if not tag_path or tag_path not in wide_lookup.index:
        return pd.Series([pd.NA] * len(competencias), index=competencias, dtype="Float64")
    row = wide_lookup.loc[tag_path]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    values = pd.to_numeric(pd.Series([row.get(competencia, pd.NA) for competencia in competencias], index=competencias), errors="coerce")
    return values.astype("Float64")


def _sum_series(wide_lookup: pd.DataFrame, competencias: list[str], short_ids: Iterable[str]) -> pd.Series:
    return _sum_existing_series([_series(wide_lookup, competencias, short_id) for short_id in short_ids])


def _empty_series(competencias: list[str]) -> pd.Series:
    return pd.Series([pd.NA] * len(competencias), index=competencias, dtype="Float64")


def _coalesce_series(primary: pd.Series, fallback: pd.Series) -> pd.Series:
    if primary.empty:
        return fallback.astype("Float64")
    if fallback.empty:
        return primary.astype("Float64")
    return primary.astype("Float64").combine_first(fallback.astype("Float64")).astype("Float64")


def _subtract_nonnegative(total: pd.Series, subtract: pd.Series) -> pd.Series:
    if total.empty:
        return total
    result = pd.to_numeric(total, errors="coerce").astype("Float64") - pd.to_numeric(subtract, errors="coerce").astype("Float64")
    result = result.where(result >= 0, 0.0)
    return result.astype("Float64")


def _dashboard_series(
    dashboard_data: Any | None,
    frame_attr: str,
    competencias: list[str],
    value_column: str,
    *,
    filter_column: str | None = None,
    filter_values: Iterable[str] | None = None,
) -> pd.Series:
    if dashboard_data is None:
        return _empty_series(competencias)
    frame = getattr(dashboard_data, frame_attr, None)
    if not isinstance(frame, pd.DataFrame) or frame.empty or "competencia" not in frame.columns or value_column not in frame.columns:
        return _empty_series(competencias)
    subset = frame.copy()
    if filter_column and filter_values is not None:
        accepted = {str(value) for value in filter_values}
        if filter_column not in subset.columns:
            return _empty_series(competencias)
        subset = subset[subset[filter_column].astype(str).isin(accepted)].copy()
    if subset.empty:
        return _empty_series(competencias)
    values = (
        subset.assign(_value=pd.to_numeric(subset[value_column], errors="coerce"))
        .groupby("competencia", dropna=False)["_value"]
        .sum(min_count=1)
        .to_dict()
    )
    return pd.Series([values.get(competencia, pd.NA) for competencia in competencias], index=competencias, dtype="Float64")


def _dashboard_over_series(dashboard_data: Any | None, competencias: list[str], serie: str) -> pd.Series:
    return _dashboard_series(
        dashboard_data,
        "default_over_history_df",
        competencias,
        "valor",
        filter_column="serie",
        filter_values=[serie],
    )


def _dashboard_aging_bucket_series(
    dashboard_data: Any | None,
    competencias: list[str],
    labels: Iterable[str],
) -> pd.Series:
    return _dashboard_series(
        dashboard_data,
        "default_aging_history_df",
        competencias,
        "valor",
        filter_column="faixa",
        filter_values=labels,
    )


def _dashboard_weighted_return_series(
    dashboard_data: Any | None,
    competencias: list[str],
    class_macro: str,
) -> pd.Series:
    if dashboard_data is None:
        return _empty_series(competencias)
    returns = getattr(dashboard_data, "return_history_df", None)
    quota_pl = getattr(dashboard_data, "quota_pl_history_df", None)
    if not isinstance(returns, pd.DataFrame) or returns.empty or "class_macro" not in returns.columns:
        return _empty_series(competencias)
    subset = returns[returns["class_macro"].astype(str).eq(class_macro)].copy()
    if subset.empty or "competencia" not in subset.columns or "retorno_mensal_pct" not in subset.columns:
        return _empty_series(competencias)
    subset["retorno_mensal_pct"] = pd.to_numeric(subset["retorno_mensal_pct"], errors="coerce")
    subset = subset.dropna(subset=["retorno_mensal_pct"])
    if subset.empty:
        return _empty_series(competencias)

    if isinstance(quota_pl, pd.DataFrame) and not quota_pl.empty and "class_macro" in quota_pl.columns and "pl" in quota_pl.columns:
        weights = quota_pl[quota_pl["class_macro"].astype(str).eq(class_macro)].copy()
        if "pl_reconciliacao_role" in weights.columns:
            weights = weights[weights["pl_reconciliacao_role"].astype(str).ne("pl_nao_reconciliado")].copy()
        key_cols = [col for col in ("competencia", "class_key") if col in subset.columns and col in weights.columns]
        if key_cols:
            weights = weights[key_cols + ["pl"]].copy()
            weights["pl"] = pd.to_numeric(weights["pl"], errors="coerce")
            merged = subset.merge(weights, on=key_cols, how="left")
            merged["weighted_return"] = merged["retorno_mensal_pct"] * merged["pl"]
            grouped = merged.groupby("competencia", dropna=False)
            weighted_values: dict[str, float] = {}
            for competencia, group in grouped:
                weight_sum = pd.to_numeric(group["pl"], errors="coerce").sum(min_count=1)
                weighted_sum = pd.to_numeric(group["weighted_return"], errors="coerce").sum(min_count=1)
                if pd.notna(weight_sum) and weight_sum > 0 and pd.notna(weighted_sum):
                    weighted_values[str(competencia)] = float(weighted_sum / weight_sum)
            if weighted_values:
                simple_values = subset.groupby("competencia", dropna=False)["retorno_mensal_pct"].mean().to_dict()
                values = {**{str(key): value for key, value in simple_values.items()}, **weighted_values}
                return pd.Series([values.get(competencia, pd.NA) for competencia in competencias], index=competencias, dtype="Float64")

    values = subset.groupby("competencia", dropna=False)["retorno_mensal_pct"].mean().to_dict()
    return pd.Series([values.get(competencia, pd.NA) for competencia in competencias], index=competencias, dtype="Float64")


def _sum_existing_series(series_list: list[pd.Series]) -> pd.Series:
    if not series_list:
        return pd.Series(dtype="Float64")
    frame = pd.concat(series_list, axis=1)
    return frame.sum(axis=1, min_count=1).astype("Float64")


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce").astype("Float64")
    den = pd.to_numeric(denominator, errors="coerce").astype("Float64")
    result = num / den.where(den > 0)
    return result.astype("Float64")


def _aging_ids(suffixes: list[str]) -> list[str]:
    bases = ["COMPMT_DICRED_AQUIS", "COMPMT_DICRED_SEM_AQUIS"]
    return [f"{base}/{suffix}" for base in bases for suffix in suffixes]


def _override_series(overrides: dict[str, Any], competencias: list[str], field: str) -> pd.Series:
    values = []
    payload = overrides.get("competencias") or {}
    for competencia in competencias:
        values.append(_to_float((payload.get(competencia) or {}).get(field)))
    return pd.Series(values, index=competencias, dtype="Float64")


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if value is pd.NA:
        return None
    text = str(value).strip()
    if text in {"", "nan", "None", "<NA>"}:
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _to_nullable(value: object) -> object:
    numeric = _to_float(value)
    return pd.NA if numeric is None else numeric


def _override_path(cnpj: str, *, overrides_dir: Path | None = None) -> Path:
    return (overrides_dir or DEFAULT_OVERRIDES_DIR) / f"{_normalize_cnpj(cnpj)}.json"


def _normalize_cnpj(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))
