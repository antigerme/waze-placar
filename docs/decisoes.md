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
dados mudaram, sem ninguém perceber. Hoje nenhum texto da página tem número
literal: ou é descrição do método, ou é medido na coleta.

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

**Achar que dava para deduzir o significado de `rankLocked` do payload.** O
campo vinha em 47 dos 172 candidatos brasileiros e o dado não dizia se era
sanção ou rotina administrativa — proporção alta demais para parecer punição,
o que puxava para o palpite de que fosse rotina. É sanção: confirmado por Champ
da comunidade brasileira. A exclusão, decidida por precaução quando o
significado era desconhecido, estava certa. Quando o campo é sobre pessoa
nomeada e o significado é ambíguo, exclua primeiro e pergunte a quem sabe —
inverter depois é barato, despublicar não é.

**Inventar o mecanismo ao dar a ressalva.** A nota de mentoria dizia que os
dois números não provam causa "porque quem procura mentor provavelmente já é
quem tenderia a continuar". A ressalva estava certa, a explicação não era
medida — e provavelmente estava invertida, já que no Waze é o mentor que
adiciona o afilhado (`AddMentee`). Dar a ressalva não autoriza inventar a razão.

**Chamar de "a caminho" quem estava parado.** O `rankCandidates` lista quem
bate o critério de edições acumuladas, não quem está editando — são coisas
diferentes, e a diferença é grande: 69 dos 120 candidatos brasileiros não
tinham nenhuma edição na janela. Pior no lugar mais visível, a coluna de quem
está mais perto: os seis primeiros estavam todos parados, o primeiro deles a
dez edições do próximo nível e sem editar havia meses. O painel prometia
movimento onde não havia nenhum. Hoje só entra quem editou na janela — entre
esses, a mediana de silêncio é de seis dias.

Vale para qualquer lista que a API rotule: o rótulo dela é sobre o acumulado, o
placar é sobre atividade. Confira em qual dos dois o painel está falando.

**Quase transformar percentual em "faltam N edições".** O `fracToNextRank` do
`rankCandidates` parece progresso em edições, e para quem sai do primeiro nível
é mesmo: o denominador dá 3.000 cravado para todos os candidatos do mundo. A
tentação era publicar "faltam N edições para o nível X" em toda a tabela.
Medindo, o denominador do segundo nível em diante muda de pessoa para pessoa —
25.735 para um, 25.270 para outro — e o que entra nessa conta não está no
payload. Hoje o script mede o limiar por nível e só cita o número onde ele é
único; nos outros mostra o percentual e diz que não sabe quanto falta.

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

**Painel de "quem voltou a editar".** Implementado e medido. Na coleta em que
foi avaliado deu zero retornos, e a decisão foi não dar painel próprio a um
número desses — hoje ele aparece como frase dentro da vigília. Fica o registro
de que a justificativa envelheceu: em 03/08/2026 foram 7. Se passar a ser
rotina, vale reabrir.

**Distância até os colegas de estado sem recortar o Brasil.** A primeira versão
misturava "cuida de outro estado" com "cuida de outro país", e o primeiro
colocado aparecia a 6.081 km. Recorta-se o Brasil antes de medir.

**Paginar `Transactions` com `nextTransactionDate`.** Parece cursor, não é:
reenviar devolve a mesma página. Verificado comparando os `daysSince`.

**Comparar a composição de tipos recente com a histórica.** As taxonomias são
diferentes — `Node`, `PermanentHazard` e `Street` não existem no `editsByType`.
A comparação não é válida e a frase que a afirmava saiu.

**Fuso de Brasília na página.** Decidido manter UTC, que é o fuso do servidor.

**Marcar só a média na tabela.** A ideia era uma linha de média para se comparar
com ela. Medindo antes de implementar, a média cai no terço superior de toda
aba, porque a distribuição é muito torta: no Histórico ela é 5.946 vezes a
mediana e deixa 91% da lista "abaixo da média" — verdade aritmética que não
informa nada e, numa página de comunidade, só desanima. Entraram as duas
réguas: a mediana parte a lista ao meio, que é onde a pergunta "sou típico?" se
responde, e a distância até a média mostra a concentração sem precisar dizer.

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
| Estreantes na janela | 84, dos quais 20 ainda ativos |
| Cobertura de área | 127 editores, 515 áreas, 4.063 células |
| Edições recentes mapeadas | 1.642 de 251 editores |
| Retenção mediana das safras maduras | 18%, entre 14% e 26% |
| Ativos fora da varredura `ALL_TIME` | 42% |
| Linhas de ranking de janela sem edição | 99% |

O `rankCandidates` entrou depois desta tabela, então ele tem os números dele, de
06/08/2026: **120 candidatos brasileiros na lista** e **90 que não apareciam em
ranking nenhum**. O total de omitidos por sanção fica aqui, não na página. Como esses 90
passaram a entrar no universo, o total de editores da próxima execução completa
vai nascer acima dos 2.534 desta tabela — a diferença é o endpoint novo, não
coleta quebrada.

O gradiente de nível é o melhor sinal de sanidade: a fatia ativa cresce forte
do N1 ao N4 — de 6% a 93% — e o N6 fica em 100%. **Não é monótono**: nesta
medição o N5 aparece abaixo do N4, 91% contra 93%. A diferença é de dois
editores e não significa nada; o que importa é o formato geral.

Isso aqui já se contradisse: o parágrafo dizia "sobe monotonicamente" com a
tabela logo acima mostrando 93% e depois 91%. E a página repetia a mesma
afirmação em prosa, escrita à mão. Hoje a página mede e diz onde quebra, e este
parágrafo descreve o que a tabela realmente mostra.

Se o gradiente perder o formato — N1 alto, N6 baixo, ou saltos grandes no meio
—, desconfie da coleta antes de desconfiar da comunidade.

---

## Não explorado

**Áreas de editores inativos.** Hoje só os ativos têm `Areas` coletada, então o
mapa mostra onde há gerente presente. Coletando dos inativos daria para achar
**área órfã** — região cujo gerente sumiu —, que é acionável para um Champ.
Custo: até 2.500 requisições a mais.

**`Transactions` dos inativos**, pelo mesmo motivo e com o mesmo custo. Menos
interessante: para quem parou, as dez últimas edições são antigas.

**Outros países.** Toda a estrutura é agnóstica menos a lista de UFs, o mapa
`ESTADOS` e o recorte do mapa. Um país novo precisa das subdivisões em ISO
3166-2, dos nomes de estado por extenso como o `rankCandidates` os escreve, e de
uma caixa geográfica.

**Os outros dois ambientes `-live`.** `Descartes-live` e `il-Descartes-live`
respondem e trazem candidatos, mas nenhum brasileiro. Só seriam úteis se o
escopo saísse do Brasil.

**Rate limiting.** Nunca foi testado o teto, de propósito. Se um dia for
necessário subir o ritmo, subir aos poucos e observar, não procurar o limite.
