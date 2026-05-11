from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any

import pandas as pd
import streamlit as st

from services import cvm_cadastro
from services.portfolio_store import (
    PortfolioFund,
    PortfolioRecord,
    build_portfolio_store,
    portfolio_basket_signature,
    portfolio_name_key,
    resolve_portfolio_store_config,
)

_cache_data = getattr(st, "cache_data", None)
if callable(_cache_data):
    _cache_data_decorator = _cache_data(show_spinner=False)
else:
    def _cache_data_decorator(func):  # type: ignore[misc]
        return func


def _secrets_to_dict() -> dict[str, Any]:
    try:
        return dict(st.secrets)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return {}


def get_portfolio_store_config():
    return resolve_portfolio_store_config(secrets_mapping=_secrets_to_dict())


def _portfolio_store_signature() -> str:
    config = get_portfolio_store_config()
    return json.dumps(
        {
            "backend": config.backend,
            "repo": config.repo,
            "branch": config.branch,
            "path": config.path,
            "local_path": config.local_path,
            "api_base_url": config.api_base_url,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


@_cache_data_decorator
def list_saved_portfolios_cached(signature: str) -> list[dict[str, Any]]:
    _ = signature
    store = build_portfolio_store(get_portfolio_store_config())
    return [portfolio.to_dict() for portfolio in store.list_portfolios()]


def list_saved_portfolios() -> list[PortfolioRecord]:
    signature = _portfolio_store_signature()
    return [PortfolioRecord.from_dict(item) for item in list_saved_portfolios_cached(signature)]


def save_portfolio_record(portfolio: PortfolioRecord) -> PortfolioRecord:
    store = build_portfolio_store(get_portfolio_store_config())
    stored = store.save_portfolio(portfolio)
    list_saved_portfolios_cached.clear()
    return stored


def delete_portfolio_record(portfolio_id: str) -> None:
    store = build_portfolio_store(get_portfolio_store_config())
    store.delete_portfolio(portfolio_id)
    list_saved_portfolios_cached.clear()


def build_portfolio_record_label_lookup(portfolios: list[PortfolioRecord]) -> dict[str, str]:
    name_counts = Counter(portfolio_name_key(portfolio.name) for portfolio in portfolios)
    exact_counts = Counter(
        (portfolio_name_key(portfolio.name), portfolio_basket_signature(portfolio.funds))
        for portfolio in portfolios
    )
    labels: dict[str, str] = {}
    for portfolio in portfolios:
        name_key = portfolio_name_key(portfolio.name)
        exact_key = (name_key, portfolio_basket_signature(portfolio.funds))
        base = f"{portfolio.name} · {len(portfolio.funds)} fundo(s)"
        if exact_counts[exact_key] > 1 or name_counts[name_key] > 1:
            base = f"{base} · ID {portfolio.id[:8]}"
        labels[portfolio.id] = base
    return labels


def build_portfolio_funds_display_df(portfolio: PortfolioRecord) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Fundo": normalize_portfolio_fund_name(fund.display_name, fund.cnpj),
                "CNPJ": format_portfolio_cnpj(fund.cnpj),
            }
            for fund in portfolio.funds
        ],
        columns=["Fundo", "CNPJ"],
    )


def render_saved_portfolio_delete_manager(
    *,
    portfolios: list[PortfolioRecord],
    key_prefix: str,
    selected_portfolio_id: str | None = None,
    on_delete=None,  # noqa: ANN001
) -> None:
    if not portfolios:
        return

    options = [portfolio.id for portfolio in portfolios]
    state_key = f"{key_prefix}_delete_portfolio_id"
    current_id = str(st.session_state.get(state_key) or "")
    if current_id not in options:
        st.session_state[state_key] = selected_portfolio_id if selected_portfolio_id in options else options[0]
    labels = build_portfolio_record_label_lookup(portfolios)

    with st.expander("Gerenciar carteiras salvas", expanded=False):
        st.caption("Remove só o preset salvo; os dados baixados permanecem.")
        selected_id = st.selectbox(
            "Carteira para revisar ou apagar",
            options=options,
            key=state_key,
            format_func=lambda value: labels.get(value, value),
        )
        selected = next((portfolio for portfolio in portfolios if portfolio.id == selected_id), None)
        if selected is None:
            return
        st.caption(
            f"ID `{selected.id[:8]}` · {len(selected.funds)} fundo(s) · "
            f"atualizada em {selected.updated_at or 'N/D'}"
        )
        st.dataframe(
            build_portfolio_funds_display_df(selected),
            hide_index=True,
            use_container_width=True,
        )
        confirm_key = f"{key_prefix}_delete_portfolio_confirm::{selected.id}"
        confirmed = st.checkbox(
            f"Confirmo que quero apagar a carteira salva '{selected.name}'.",
            key=confirm_key,
        )
        if st.button(
            "Apagar carteira salva",
            key=f"{key_prefix}_delete_portfolio_button::{selected.id}",
            type="secondary",
            use_container_width=False,
        ):
            if not confirmed:
                st.warning("Marque a confirmação antes de apagar a carteira.")
                return
            delete_portfolio_record(selected.id)
            st.session_state.pop(state_key, None)
            st.session_state.pop(confirm_key, None)
            if callable(on_delete):
                on_delete(selected.id)
            st.toast(f"Carteira salva '{selected.name}' apagada.")
            st.rerun()


@_cache_data_decorator
def load_fidc_catalog_cached() -> pd.DataFrame:
    direct_loader = getattr(cvm_cadastro, "list_fidc_catalog", None)
    if callable(direct_loader):
        return direct_loader()

    raw_loader = getattr(cvm_cadastro, "_load_cad_fidc", None)
    if not callable(raw_loader):
        return pd.DataFrame(columns=["cnpj_fundo", "nome_fundo", "situacao"])

    df = raw_loader()
    if df is None or df.empty:
        return pd.DataFrame(columns=["cnpj_fundo", "nome_fundo", "situacao"])

    strip_digits = getattr(cvm_cadastro, "_strip_digits", lambda value: "".join(ch for ch in str(value or "") if ch.isdigit()))
    clean = getattr(cvm_cadastro, "_clean", lambda value: str(value or "").strip())

    cnpj_col = next(
        (column for column in df.columns if str(column).strip().upper() == "CNPJ_FUNDO"),
        None,
    )
    if cnpj_col is None:
        return pd.DataFrame(columns=["cnpj_fundo", "nome_fundo", "situacao"])

    name_candidates = ["DENOM_SOCIAL", "DENOM_COMERC", "NM_FUNDO", "NOME_FUNDO"]
    name_col = next((column for column in name_candidates if column in df.columns), None)
    situacao_col = next((column for column in ("SIT", "SITUACAO") if column in df.columns), None)

    catalog = pd.DataFrame(
        {
            "cnpj_fundo": df[cnpj_col].map(strip_digits),
            "nome_fundo": df[name_col].map(clean) if name_col else "",
            "situacao": df[situacao_col].map(clean) if situacao_col else "",
        }
    )
    catalog = catalog[catalog["cnpj_fundo"].astype(str).str.len() == 14].copy()
    if name_col:
        catalog["nome_fundo"] = catalog["nome_fundo"].replace("", pd.NA)
    catalog["nome_fundo"] = catalog["nome_fundo"].fillna(catalog["cnpj_fundo"])
    return catalog.drop_duplicates(subset=["cnpj_fundo"], keep="last").sort_values(["nome_fundo", "cnpj_fundo"]).reset_index(drop=True)


def get_portfolio_status_caption() -> str:
    config = get_portfolio_store_config()
    if config.backend == "github" and config.repo:
        return f"Carteiras persistidas via GitHub: `{config.repo}` · branch `{config.branch}`."
    return "Carteiras persistidas localmente neste ambiente."


def _catalog_name_lookup(catalog_df: pd.DataFrame) -> dict[str, str]:
    if catalog_df is None or catalog_df.empty:
        return {}
    return catalog_df.set_index("cnpj_fundo")["nome_fundo"].to_dict()


def format_portfolio_cnpj(cnpj: str) -> str:
    digits = re.sub(r"\D", "", str(cnpj or ""))
    if len(digits) != 14:
        return digits or str(cnpj or "").strip()
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def normalize_portfolio_fund_name(display_name: str, cnpj: str) -> str:
    digits = re.sub(r"\D", "", str(cnpj or ""))
    formatted_cnpj = format_portfolio_cnpj(digits)
    text = re.sub(r"\s+", " ", str(display_name or "").strip())
    if not text:
        return formatted_cnpj if formatted_cnpj else digits
    for suffix in (formatted_cnpj, digits):
        if suffix and text.endswith(suffix):
            candidate = re.sub(r"[\s·|()/:-]+$", "", text[: -len(suffix)].strip())
            if candidate:
                text = candidate
                break
    return text


def format_portfolio_fund_label(
    *,
    display_name: str,
    cnpj: str,
    status: str | None = None,
) -> str:
    name = normalize_portfolio_fund_name(display_name, cnpj)
    formatted_cnpj = format_portfolio_cnpj(cnpj)
    if not name or name == cnpj or name == formatted_cnpj:
        base = formatted_cnpj
    else:
        base = f"{name} · {formatted_cnpj}"
    if status:
        return f"{base} · {status}"
    return base


def enrich_portfolio_funds_with_catalog(
    funds: list[PortfolioFund] | tuple[PortfolioFund, ...],
    catalog_df: pd.DataFrame | None = None,
) -> list[PortfolioFund]:
    resolved_catalog = catalog_df if catalog_df is not None else load_fidc_catalog_cached()
    name_lookup = _catalog_name_lookup(resolved_catalog)
    enriched: list[PortfolioFund] = []
    for fund in funds:
        canonical_name = str(name_lookup.get(fund.cnpj) or "").strip()
        if not canonical_name:
            canonical_name = normalize_portfolio_fund_name(fund.display_name, fund.cnpj)
        enriched.append(
            PortfolioFund(
                cnpj=fund.cnpj,
                display_name=canonical_name,
            )
        )
    return enriched


def build_portfolio_funds_from_cnpjs(
    cnpjs: list[str],
    catalog_df: pd.DataFrame | None = None,
) -> list[PortfolioFund]:
    """Parse a list of raw CNPJ strings into PortfolioFund objects, enriching names from the CVM catalog."""
    resolved_catalog = catalog_df if catalog_df is not None else load_fidc_catalog_cached()
    name_lookup = _catalog_name_lookup(resolved_catalog)
    funds: list[PortfolioFund] = []
    for raw_cnpj in cnpjs:
        digits = re.sub(r"\D", "", str(raw_cnpj or ""))
        if len(digits) != 14:
            continue
        funds.append(
            PortfolioFund(
                cnpj=digits,
                display_name=str(name_lookup.get(digits) or format_portfolio_cnpj(digits)),
            )
        )
    return funds


def build_catalog_option_lookup(
    catalog_df: pd.DataFrame,
) -> tuple[list[str], dict[str, PortfolioFund]]:
    """Return ordered labels + {label -> PortfolioFund} for use in Streamlit multiselects."""
    if catalog_df is None or catalog_df.empty:
        return [], {}
    option_lookup: dict[str, PortfolioFund] = {}
    for row in catalog_df.itertuples(index=False):
        cnpj = re.sub(r"\D", "", str(getattr(row, "cnpj_fundo", "") or ""))
        if len(cnpj) != 14:
            continue
        name = normalize_portfolio_fund_name(str(getattr(row, "nome_fundo", "") or cnpj).strip() or cnpj, cnpj)
        label = format_portfolio_fund_label(display_name=name, cnpj=cnpj)
        option_lookup[label] = PortfolioFund(cnpj=cnpj, display_name=name)
    return list(option_lookup.keys()), option_lookup
