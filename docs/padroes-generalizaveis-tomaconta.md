# Padrões generalizáveis do Toma Conta

## Modelo FIDC

- Toda série de gráfico cujo nome não seja autoexplicativo precisa de definição visível ao lado do gráfico; hover é complemento, não substituto.
- Vocabulário de uma aba deve ficar centralizado em constante única, evitando strings literais espalhadas para cotas, métricas e séries.
- Datas iniciais de simulação não devem ser hard-coded; devem ser ancoradas em uma fonte dinâmica, como último pregão carregado, com override explícito do usuário.
- Ágio em compra de recebível deve ser absorvido na taxa efetiva quando o objetivo é simulação econômica simples, salvo razão contábil para coluna separada.
- Quando houver ágio, a base de exposição em default deve refletir o preço pago, não apenas o valor de face.
- A mecânica de uma aba financeira precisa declarar o que está tratado no motor, o que está documentado e a direção do viés das simplificações.
- Quando uma mudança altera lógica central, reescrever a seção da mecânica em vez de inserir uma frase isolada.
- Documentos de mecânica de modelo financeiro devem incluir bloco de limitações conhecidas em backlog.
