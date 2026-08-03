# A API do Waze, como ela realmente se comporta

Tudo aqui foi verificado contra a API viva, não deduzido do código do cliente.
Onde há número, ele foi medido; onde algo não foi testado, está dito.

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
chave de ordenação. Medido: **99% das linhas dos rankings de janela são de quem
não editou nada no período.**

**Rankings estaduais não se sobrepõem.** Verificado: 3.000 editores em seis
rankings estaduais, nenhum repetido. Isso deixa atribuir a UF de graça. E quem
está no top 500 nacional está necessariamente no top 500 do próprio estado,
porque o estado é subconjunto do país.

**Varrer só `ALL_TIME` não basta.** Ele ordena por pontos acumulados, então
quem edita muito hoje mas tem pouco histórico fica fora. Medido: **42% dos
editores ativos nos rankings de janela não aparecem na varredura `ALL_TIME`.**

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
  último é hoje e vem parcial. Verificado: os 2.534 perfis coletados têm
  exatamente 91 posições.
- `rank` — é o `level` do ranking **menos 1**.
- `editsByType` — sete categorias. **`count` vem `null` com frequência** (11 mil
  campos nulos numa coleta) e a soma não fecha com `edits`.
- `mentees[]` — **truncada em 10**. Verificado nos três mentores com mais que
  isso: todos cortados em exatamente 10. Use `Mentoring/Mentees`.
- `firstEditDate`, `isMentor`, `menteesCount`, `forumPosts`, `lastEditEnv`.

Os números do vetor diário **não batem** com as janelas do ranking. Num teste,
30 dias somados deram 27.936 contra 28.244 do `PAST_MONTH`; na semana a
distância foi maior. São relógios ou definições diferentes — use um ou outro,
não misture.

---

## Áreas gerenciadas

```
GET /row-Descartes/app/UserProfile/Areas?userID=<id>
```

**Aqui o ambiente importa**, ao contrário do perfil. Para editor brasileiro só
`row-Descartes` devolve polígono; `Descartes` e `il-Descartes` respondem 200 com
`managedAreas` vazio. Isso já causou uma coleta zerada neste projeto.

Os polígonos são reais, não caixas: **até 3.445 vértices**. Embutir a geometria
crua numa página é inviável — o projeto rasteriza numa grade.

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
de anos atrás: a coleta trouxe transação de **3.927 dias**. Filtre por janela.

A geocodificação é parcial: **cerca de 69%** trazem `city`.

---

## Mentoria

```
GET /{ambiente}/app/Mentoring/Mentees?userID=<id>     # lista completa
GET /row-Descartes/app/Mentoring/NewEditors           # sem parâmetro nenhum
GET /{ambiente}/app/Mentoring/Communities?mentorID=   # só o link do fórum
```

`Mentees` devolve a lista inteira, sem o corte de 10 do perfil.

**`NewEditors` é o achado mais importante para cobertura.** Devolve editores
recém-chegados — 319 brasileiros de 2025 e 2026 numa coleta — e **316 deles não
apareciam em nenhum dos 84 rankings**, porque quem tem três edições não pontua o
bastante para entrar. Sem esse endpoint o funil de entrada some do placar, e é
fácil concluir, errado, que a comunidade parou de receber gente. A lista é
nacional: idêntica seja qual for o mentor que consulta, e não precisa de
parâmetro.

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

Uma execução completa hoje: 84 rankings + 1 lista de novatos + ~2.500 perfis +
23 listas de afilhados + ~90 perfis de afilhados + ~290 áreas + ~290 transações.
