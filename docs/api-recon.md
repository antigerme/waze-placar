# A API do Waze, como ela realmente se comporta

Tudo aqui foi verificado contra a API viva, não deduzido do código do cliente.
Onde há número, ele foi medido; onde algo não foi testado, está dito.

**Sobre os números deste documento.** Uns descrevem a API e não mudam sozinhos
— o teto de 500 linhas, os três valores do `lookbackPeriod`, as 91 posições do
vetor diário. Outros são o tamanho da comunidade brasileira no dia em que
foram medidos, e envelhecem: esses vêm marcados com **`medido em 03/08/2026`**
e valem como ordem de grandeza, não como fato corrente. Se você precisa do
número de hoje, ele está na página gerada, que o recalcula a cada execução.

Dois backends distintos atendem o placar, e eles não se comportam igual:

- **`/_user/api/…`** serve os rankings.
- **`/{ambiente}/app/…`** é o Descartes, e serve perfil, áreas, edições e
  mentoria. O `{ambiente}` é `Descartes`, `row-Descartes` (rest of world) ou
  `il-Descartes`.

Os dois exigem sessão. Sem cookie, o ranking devolve 401 e o Descartes 403.

---

## Rankings

```
GET /_user/api/leaderboard
```

| Parâmetro | Valores | Efeito |
|---|---|---|
| `lookbackPeriod` | `ALL_TIME`, `PAST_MONTH`, `PAST_WEEK` | Janela |
| `countryCode` | ISO 3166-1 alpha-2 | Ranking nacional |
| `stateCode` | **ISO 3166-2** (`BR-SP`) | Subdivisão; exige `countryCode` |
| `wazerCountryLeaderboard` | `true` | Nacional do próprio usuário |
| `show_editor_levels` | `true`/`false` | **Nenhum** — `level` vem dos dois jeitos |

**A armadilha do `lookbackPeriod`.** Só aqueles três valores existem. Qualquer
outro — `PAST_YEAR`, `LAST_7_DAYS`, lixo puro — devolve **200 com o payload de
`ALL_TIME`**, sem erro. Sondar o parâmetro com nomes inventados faz ele parecer
inerte. Foi assim que a primeira leitura deste projeto concluiu, errado, que
não havia janela nenhuma.

**Teto de 500 linhas, sem paginação.** `offset`, `page`, `limit`, `count` e
`start` são todos ignorados.

**Ordena por `points`, não por edições.** `points` soma dirigir e editar, e é a
chave de ordenação. Por isso a maior parte de um ranking de janela é gente que
dirigiu e não editou: **99% das linhas** (medido em 03/08/2026). A página
recalcula essa fração a cada execução em vez de repetir esta.

**Rankings estaduais não se sobrepõem.** Verificado em seis rankings estaduais,
3.000 editores, nenhum repetido (medido em 03/08/2026). Isso deixa atribuir a UF
de graça. E quem está no top 500 nacional está necessariamente no top 500 do
próprio estado, porque o estado é subconjunto do país.

**Varrer só `ALL_TIME` não basta.** Ele ordena por pontos acumulados, então
quem edita muito hoje mas tem pouco histórico fica fora — e não é uma minoria
desprezível: **42% dos editores ativos nos rankings de janela** não apareciam
na varredura `ALL_TIME` (medido em 03/08/2026). É por isso que o coletor varre
as três janelas em vez de só o acumulado.

### Resposta

```jsonc
{
  "record": [{
    "userId": "88679", "username": "asterix06", "countryCode": "IT",
    "points": "23753477",      // dirigir + editar, na janela
    "mapEditCount": "6500610", // edições na janela
    "level": "6",              // AUSENTE para quem nunca editou
    "moodUrl": "…/$mood.mood_id/…"
  }],
  "wazerDetails": { },          // o próprio chamador
  "rank": 3                     // posição do chamador; ausente em subdivisão
}
```

Números vêm como string. **`level` é opcional por registro** — aparece só para
quem tem `mapEditCount > 0`.

---

## Perfil

```
GET /{ambiente}/app/UserProfile/Profile?username=<nome>
```

Indiferente ao ambiente: os três devolvem idêntico. Funciona para qualquer
editor. Usuário inexistente devolve **500**, não 404.

Campos que importam:

- **`editingActivity`** — 91 inteiros, um por dia. Índice 0 é 90 dias atrás, o
  último é hoje e vem parcial. O tamanho é fixo: numa varredura de 2.534 perfis,
  todos tinham exatamente 91 posições (medido em 03/08/2026).
- `rank` — é o `level` do ranking **menos 1**.
- `editsByType` — sete categorias. **`count` vem `null` com frequência** — na
  ordem de 11 mil campos nulos numa coleta inteira (medido em 03/08/2026) — e a
  soma não fecha com `edits`.
- `mentees[]` — **truncada em 10**. Verificado nos três mentores com mais que
  isso: todos cortados em exatamente 10. Use `Mentoring/Mentees`.
- `firstEditDate`, `isMentor`, `menteesCount`, `forumPosts`, `lastEditEnv`.

Os números do vetor diário **não batem** com as janelas do ranking. Num teste,
30 dias somados deram 27.936 contra 28.244 do `PAST_MONTH` (medido em
03/08/2026); na semana a distância foi maior. O que importa não é o tamanho da
diferença, que muda a cada dia, mas o fato de existir: são relógios ou
definições diferentes — use um ou outro, não misture.

---

## Áreas gerenciadas

```
GET /row-Descartes/app/UserProfile/Areas?userID=<id>
```

**Aqui o ambiente importa**, ao contrário do perfil. Para editor brasileiro só
`row-Descartes` devolve polígono; `Descartes` e `il-Descartes` respondem 200 com
`managedAreas` vazio. Isso já causou uma coleta zerada neste projeto.

Os polígonos são reais, não caixas: o maior encontrado tinha **3.445 vértices**
(medido em 03/08/2026). Embutir a geometria crua numa página é inviável — o
projeto rasteriza numa grade.

---

## Edições recentes

```
GET /row-Descartes/app/UserProfile/Transactions?userID=<id>
```

As dez últimas edições, com `centroid` (ponto GeoJSON), `street`, `city`,
`country`, `daysSince` e `operations[]` com `actionType` e `objectType`.

**A paginação não existe.** O campo `nextTransactionDate` parece cursor, mas
reenviá-lo devolve a mesma página — conferido comparando os `daysSince` das duas
chamadas.

**"Dez últimas" não quer dizer recentes.** Para quem edita pouco elas podem ser
de anos atrás: a coleta trouxe transação de **3.927 dias** (medido em
03/08/2026). Filtre por janela.

**A geocodificação é parcial.** Boa parte das transações vem sem `city`, então
qualquer contagem por cidade cobre só um pedaço das edições. A fração exata
muda de coleta para coleta; a página a mede e informa junto do painel, em vez
de fixar um número aqui.

---

## Candidatos a subir de nível

```
GET /row-Descartes-live/app/info/rankCandidates      # sem parâmetro nenhum
```

É o que alimenta `waze.com/pt-BR/dashboard/editor`. **Repare no sufixo
`-live`**, que não existe em nenhum outro endpoint daqui: `Descartes-live`,
`row-Descartes-live` e `il-Descartes-live` são ambientes à parte. Brasileiro só
aparece em `row-Descartes-live` — os outros dois devolvem zero brasileiros —,
então o país inteiro sai em **uma requisição**.

Cada registro:

```jsonc
{
  "userName": "fulano",
  "curRank": 2,              // nível MENOS 1, igual ao `rank` do perfil
  "candidateRank": 4,        // nível a que é candidato, também menos 1
  "fracToNextRank": 0.978,   // progresso até o próximo nível; 1,0 é o limiar
  "mapEditCount": 98520,
  "countryName": "Brazil", "stateName": "Goiás",   // estado POR EXTENSO
  "lastEditDate": 1444363272215,
  "lastEditPoint": {"type": "Point", "coordinates": [-49.2, -16.6]},
  "qualificationDate": null, // vem nulo em cerca de metade dos casos
  "areaManager": false,
  "mapEditingBanned": false,
  "rankLocked": false
}
```

**`curRank` é o nível menos 1.** Verificado cruzando com os perfis já
coletados: bateu em 40 de 40 editores presentes nas duas fontes.

**`fracToNextRank` é razão contra um limiar, e o limiar não é sempre o mesmo.**
Dividindo `mapEditCount` pela fração sai o denominador. Para quem está no
primeiro nível ele deu **3.000 edições para todos os 1.187 candidatos do
mundo**, sem exceção. Acima disso o valor muda de pessoa para pessoa — no
segundo nível apareceram 25.735, 25.653, 25.270 e assim por diante. O que entra
nessa conta não está no payload, então **não dá para dizer "faltam N edições"**
fora do primeiro nível. O projeto mede o denominador por nível e só cita o
número onde ele é único.

**O estado vem por extenso**, não em ISO 3166-2 como no ranking. Daí o mapa
`ESTADOS` no `waze.py`.

**A lista alcança quem o ranking não alcança.** Numa coleta, 132 dos 172
candidatos brasileiros não estavam em nenhum dos 84 rankings — a maioria de
nível baixo, que não pontua o bastante para entrar, mas um deles com 665.733
edições de carreira (medido em 06/08/2026).

### Campos que não são coletados

`mapEditingBanned` e `rankLocked` são **os dois sanção** aplicada a uma pessoa
nomeada — o segundo confirmado por Champ da comunidade brasileira, que é quem
tem autoridade sobre isso; pelo payload não dava para distinguir sanção de
rotina administrativa. **Não entram em dataset nem na página.**

Quem tem qualquer um dos dois é removido da lista inteira pelo
`coleta_candidatos`, não só do campo: esconder a marca não bastaria, porque
aparecer numa lista de "prestes a subir de nível" já diria algo sobre quem está
impedido de subir. Sobrevive só a contagem de quantos saíram — sem nome e sem
motivo.

`lastEditPoint` é a coordenada da última edição de uma pessoa nomeada. Não é
coletado: onde o projeto mapeia posição, ele rasteriza numa grade de dezenas de
quilômetros e nunca mostra ponto por pessoa.

---

## Mentoria

```
GET /{ambiente}/app/Mentoring/Mentees?userID=<id>     # lista completa
GET /row-Descartes/app/Mentoring/NewEditors           # sem parâmetro nenhum
GET /{ambiente}/app/Mentoring/Communities?mentorID=   # só o link do fórum
```

`Mentees` devolve a lista inteira, sem o corte de 10 do perfil.

**`NewEditors` é o achado mais importante para cobertura.** Devolve editores
recém-chegados que os rankings não mostram, porque quem tem três edições não
pontua o bastante para entrar. A desproporção é o ponto: numa coleta, 319
brasileiros na lista e **316 deles ausentes dos 84 rankings** (medido em
03/08/2026). Sem esse endpoint o funil de entrada some do placar, e é fácil
concluir, errado, que a comunidade parou de receber gente. A lista é nacional:
idêntica seja qual for o mentor que consulta, e não precisa de parâmetro.

`AddMentee` e `ArchiveMentee` existem e **alteram estado** — nunca foram
chamados aqui.

---

## Sessão

**Ela se renova sozinha.** O Descartes responde os perfis com `Set-Cookie` de
`_web_session`: a sessão é rolante. Gravar o cookie jar de volta no arquivo ao
fim da execução é o que dispensa reexportar do navegador. Verificado em três
execuções seguidas, com o token rotacionando e a seguinte autenticando com o que
a anterior gravou.

**O que a renovação não faz:** empurrar o prazo absoluto do cookie. Ele fica
fixo na data em que a sessão nasceu no navegador, cerca de 30 dias. O que a
rotação sustenta é o tempo ocioso do servidor, curto.

**Os dois backends expiram em ritmos diferentes.** Já foi observado o ranking
respondendo 200 enquanto todo perfil devolvia 403 com
`"This operation is not allowed by guest user"`. Tratar 403 como "sessão morta"
e abortar tudo é errado — o placar ainda é coletável.

---

## Endpoints com PII, fora de uso

- `/_user/api/user` e `/il-UsersProfile/app/userInfo` — perfil do **próprio
  chamador**: nome completo, e-mail, cidade, última coordenada, último login.
  Ambos ignoram um parâmetro `userId`, então não servem para consultar
  terceiros. Nada dali entra em dataset.
- `/_user/api/trip` — histórico de navegação do próprio usuário, com origem e
  destino nomeados.
- `/web_api/request_info` — geo-IP do visitante; devolve `region` e
  `regionSubdivision` (formato `BRBA`, sem hífen).

---

## Ritmo

Nenhum rate limiting foi observado, mas isso **não foi testado a fundo** de
propósito: descobrir o teto castigando a infraestrutura do Waze é exatamente o
que não se quer fazer. O coletor usa throttle global com jitter de 0,45 a 1,15 s
entre requisições — ~1,25 req/s medidos — e embaralha a ordem dos editores para
o tráfego não desenhar a sequência do ranking.

O volume de uma execução completa é fixo só nas duas primeiras etapas — 84
rankings e 1 lista de novatos. As outras acompanham o tamanho da comunidade:
um perfil por editor do universo, uma lista por mentor, uma área e uma lista de
transações por editor ativo. Em 03/08/2026 isso dava ~2.500 perfis, 23 listas de
afilhados, ~90 perfis de afilhados, ~290 áreas e ~290 transações. Os números do
dia saem no `--quiet` desligado, e a tabela de ordens de grandeza do
`docs/decisoes.md` serve de canário.
