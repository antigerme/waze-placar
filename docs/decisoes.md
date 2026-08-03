# Decisões, becos sem saída e ordens de grandeza

O que a referência da API não cobre: por que o projeto é como é, o que já foi
testado e descartado, e com que números uma execução saudável se parece.

Escrito para evitar que alguém — inclusive eu, numa sessão nova — refaça
caminho que já foi andado.

---

## Erros que este projeto já cometeu

Cada um destes custou uma conclusão errada antes de virar linha de código.
Estão aqui porque são fáceis de repetir.

**Concluir que o `lookbackPeriod` era inerte.** Foi sondado com valores
inventados (`LAST_7_DAYS` e afins), o servidor respondeu 200 com o payload de
`ALL_TIME`, e a leitura foi "o parâmetro não funciona". Funciona; só existem
três valores. Sondar enum inventando nome não prova nada quando a API não
valida entrada.

**Achar que o funil de entrada tinha secado.** O universo vinha só dos
rankings, que excluem novato por construção — quem tem três edições não pontua
o bastante para entrar. A conclusão "16 novos no último ano, a comunidade parou
de receber gente" estava errada por amostragem: `Mentoring/NewEditors` lista
319. Antes de afirmar que algo não existe, verifique se a fonte conseguiria
mostrá-lo.

**Quase publicar que mentoria dá 100% de retenção.** Só 10 dos 88 afilhados
estavam no universo, e estar no universo já exige ter aparecido num ranking —
ou seja, a amostra era só de quem deu certo. Buscando o perfil dos que faltavam,
36% contra 11%. Sempre pergunte por que um registro está na amostra.

**Validar layout por métrica em vez de olhar.** Checagens em Python dizendo
"sem overflow" enquanto a tabela principal estourava o container em todas as
larguras — o sintoma estava escondido atrás de barras de rolagem que pareciam
intencionais. Daí o `scripts/auditar-layout.mjs`.

**Deixar afirmação escrita à mão na página.** Textos como "não há pico de fim
de semana" e "as safras recentes aparecem mais altas" ficaram falsos quando os
dados mudaram, sem ninguém perceber. Hoje não há número literal na prosa da
página: ou é descrição do método, ou é medido na coleta.

**Descartar dado na normalização.** O `normaliza_perfil` guardava
`menteesCount` e jogava fora a lista `mentees[]` que vinha na mesma resposta.
A análise de mentoria ficou impossível até alguém notar. Coletar é caro;
descartar campo na entrada é desperdício silencioso.

**Publicar zero em vez de não publicar.** O `--sem-perfis` saía com código 0 e
uma página inteira de zeros: KPIs zerados, as quatro abas dizendo zero editor,
painéis afirmando que ninguém editou, e "1 edições em 90 dias" — a guarda de
divisão por zero vazando para dentro do texto. Pior, a mensagem de erro do
próprio `placar.py` recomendava a flag quando o Descartes recusava a sessão,
conselho que trocava a página boa de ontem por essa. Zero medido e zero por não
ter medido são coisas diferentes: hoje a página detecta que não há vetor diário
e diz que só tem o acumulado, em vez de afirmar ausência de atividade.

**Checar só metade do texto e achar que checou tudo.** A regra "nada de número
à mão" existia desde cedo, e o `verificar.py` a cobrava — mas só dentro de
`<p>` e `<h2>`. A maior parte do texto da página não mora lá: mora nas dicas de
hover, nos `title=` das colunas, nos rótulos das abas e nos KPIs. Passaram
"últimos 90 dias", "45 anteriores", "15 blocos de 6 dias", "50 pessoas", "60 ou
mais dos últimos 90 dias" — uma dúzia de lugares que ficariam falsos no dia em
que a constante mudasse, com a verificação dando ok o tempo todo. Uma checagem
que cobre parte do alvo é pior que nenhuma: ela dá confiança.

**Afirmar o formato do dado, não só o valor.** A página dizia que o gradiente
de atividade por nível "sobe sem exceção do nível 1 ao 6". Era verdade quando
foi escrito. Mas o `decisoes.md` já registrava, duas seções abaixo, que esse
gradiente é o canário de coleta quebrada — ou seja, o dia em que a frase ficar
falsa é exatamente o dia em que ela mais engana. Hoje o script confere e diz
onde quebra. Vale para todo "sobe", "é raro", "quase todos": meça, ou não
escreva.

**Inventar o mecanismo ao dar a ressalva.** A nota de mentoria dizia que os
dois números não provam causa "porque quem procura mentor provavelmente já é
quem tenderia a continuar". A ressalva estava certa, a explicação não era
medida — e provavelmente estava invertida, já que no Waze é o mentor que
adiciona o afilhado (`AddMentee`). Dar a ressalva não autoriza inventar a razão.

**Auditar layout com número de brinquedo.** O `auditar-layout.mjs` passava
porque a página de teste tinha KPI de cinco dígitos. Com o total real, de oito,
o cartão vazava em 390 e 768px. A auditoria só enxerga o que está na página que
você entrega a ela — teste com a ordem de grandeza real, que está na tabela
mais abaixo.

---

## Caminhos testados e descartados

**Snapshot e diff de `ALL_TIME`.** Funcionava e resolvia qualquer janela, não
só as três da API. Removido quando o escopo passou a ser "sem armazenamento".
Continua sendo a melhor saída se um dia houver onde guardar — o código está no
histórico do git, antes do commit que reduziu o escopo para o Brasil.

**Painel de "quem voltou a editar".** Implementado e medido: zero retornos no
período. O número aparece como frase dentro da vigília, mas painel próprio para
mostrar zero não se justifica.

**Distância até os colegas de estado sem recortar o Brasil.** A primeira versão
misturava "cuida de outro estado" com "cuida de outro país", e o primeiro
colocado aparecia a 6.081 km. Recorta-se o Brasil antes de medir.

**Paginar `Transactions` com `nextTransactionDate`.** Parece cursor, não é:
reenviar devolve a mesma página. Verificado comparando os `daysSince`.

**Comparar a composição de tipos recente com a histórica.** As taxonomias são
diferentes — `Node`, `PermanentHazard` e `Street` não existem no `editsByType`.
A comparação não é válida e a frase que a afirmava saiu.

**Fuso de Brasília na página.** Decidido manter UTC, que é o fuso do servidor.

---

## Ordens de grandeza

Referência de uma execução saudável em 03/08/2026. Servem de canário: se a
próxima divergir muito de alguma, provavelmente quebrou coleta, não mudou o
Brasil.

| | |
|---|---|
| Universo | 2.534 editores |
| Ativos em 90 / 30 dias | 291 / 200 |
| Edições em 90 dias | 1.690.773 |
| Concentração no top 50 | 81% |
| Estados com fator de ônibus 1 | 20 de 27 |
| Ativos por nível, N1→N6 | 6%, 21%, 53%, 93%, 91%, 100% |
| Mentores / afilhados nomeados | 23 / 105 |
| Ativos: apadrinhados / demais | 36% / 11% |
| Estreantes na janela | 83, dos quais 19 ainda ativos |
| Cobertura de área | 109 editores, 481 áreas, 4.063 células |
| Edições recentes mapeadas | 1.642 de 251 editores |
| Retenção mediana das safras maduras | 18%, entre 14% e 26% |
| Ativos fora da varredura `ALL_TIME` | 42% |
| Linhas de ranking de janela sem edição | 99% |

O gradiente de nível é o mais estável de todos e o melhor sinal de sanidade:
ele sobe monotonicamente e o N6 fica em 100%. Se ele quebrar, desconfie da
coleta antes de desconfiar da comunidade.

---

## Não explorado

**Áreas de editores inativos.** Hoje só os ativos têm `Areas` coletada, então o
mapa mostra onde há gerente presente. Coletando dos inativos daria para achar
**área órfã** — região cujo gerente sumiu —, que é acionável para um Champ.
Custo: até 2.500 requisições a mais.

**`Transactions` dos inativos**, pelo mesmo motivo e com o mesmo custo. Menos
interessante: para quem parou, as dez últimas edições são antigas.

**Outros países.** Toda a estrutura é agnóstica menos a lista de UFs e o
recorte do mapa. Um país novo precisa das subdivisões em ISO 3166-2 e de uma
caixa geográfica.

**Rate limiting.** Nunca foi testado o teto, de propósito. Se um dia for
necessário subir o ritmo, subir aos poucos e observar, não procurar o limite.
