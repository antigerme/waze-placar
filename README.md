# waze-placar

Ressuscitando o placar dos editores de mapa do Waze — Brasil.

O Waze aposentou o placar público dos editores, mas
`https://www.waze.com/leaderboard` só foi desvinculado da navegação: a página
ainda renderiza e a API por trás dela ainda serve dados. Este projeto lê essa
API ao vivo e remonta o placar que a comunidade perdeu.

Sem banco, sem servidor, sem estado. Um comando lê tudo do Waze e escreve um
HTML autocontido que abre em qualquer lugar.

## Uso

Precisa de Python 3.11+, nada além da biblioteca padrão. A autenticação é o
cookie de sessão de uma conta logada no `waze.com`, em formato Netscape —
por padrão em `/tmp/cookies.txt`.

```bash
python3 scripts/placar.py                      # gera placar.html
python3 scripts/placar.py --print              # tabela no terminal
python3 scripts/placar.py --period PAST_WEEK   # só uma janela
python3 scripts/placar.py --json dados.json    # dados crus junto
python3 scripts/placar.py --cookies ~/cookies.txt --out /var/www/placar.html
```

Uma execução completa são 84 requisições e leva ~40 s.

## Rodando diariamente no cron

```cron
17 5 * * * /usr/bin/flock -n /tmp/waze-placar.lock /usr/bin/python3 /home/user/waze-placar/scripts/placar.py --out /var/www/waze-placar/index.html --quiet >> /var/log/waze-placar.log 2>&1
```

Caminhos absolutos porque o cron roda com um ambiente mínimo — sem `PATH` útil,
sem as variáveis do shell de login. O `flock -n` evita dois processos ao mesmo
tempo se um dia uma execução travar. O `--quiet` corta o progresso por ranking
mas mantém o resumo, que é o que vale no log.

Antes de agendar, rode uma vez na mão para confirmar cookie e permissão.

### O que o script garante sozinho

**Publicação atômica.** A página é escrita num temporário no mesmo diretório e
só então renomeada por cima. Ninguém pega HTML pela metade, e o temporário fica
ao lado do destino de propósito: um arquivo movido de `/tmp` carregaria o rótulo
SELinux de lá e o httpd responderia 403.

**Permissão explícita.** O arquivo sai `0644` mesmo se o cron rodar com umask
restritiva — senão o httpd leva 403 num arquivo que existe.

**Nada de página degradada.** Se algum dos 28 rankings não responder depois das
tentativas, o script aborta com saída 1 e **não escreve nada** — a página do dia
anterior continua no ar. O mesmo vale para cookie expirado: HTTP 401 encerra
antes de tocar no destino. Para publicar mesmo incompleto, `--allow-partial`.

### O que depende de você

- **Cookies legíveis pelo usuário do cron.** Se você exporta como seu usuário
  em modo 600 e o cron roda como root, tudo bem. Se roda como outro usuário,
  ajuste dono ou modo do `/tmp/cookies.txt`.
- **Contexto SELinux do diretório**, se ele foi criado à mão:

  ```bash
  sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/waze-placar(/.*)?"
  sudo restorecon -Rv /var/www/waze-placar
  ```

- **Rotação do log**, se `/var/log/waze-placar.log` incomodar com o tempo.

## O que o placar mostra

Três abas, que são exatamente as três janelas que a API oferece:

| Aba | Janela da API | Editores no Brasil |
|-----|---------------|--------------------|
| Histórico | `ALL_TIME` | ~2.180 |
| Mês | `PAST_MONTH` | ~77 |
| Semana | `PAST_WEEK` | ~79 |

Cada janela é varrida em 28 rankings — o nacional e os 27 estaduais — porque a
API devolve no máximo 500 linhas por ranking e não tem paginação. A varredura
estadual é o que leva o histórico de 500 para ~2.180 editores.

Como os rankings estaduais **não se sobrepõem** (verificado: 3.000 editores em
6 estados, zero repetição), a UF de cada editor sai de graça da varredura. A
lista do próprio Waze não mostra isso.

## As limitações, que são do Waze e não daqui

**Os rankings ordenam por pontos, não por edições.** `points` é a pontuação
combinada de dirigir e editar, e é a chave de ordenação de todo ranking. As 500
vagas são disputadas por motorista também. O placar reordena por edições e
descarta quem tem zero, mas não consegue recuperar quem ficou fora das 500
linhas de origem.

**Janela curta é quase só motorista.** O efeito acima piora quanto menor a
janela: editores são 45% do ranking histórico do Brasil, mas 8% do mensal. Daí
a diferença brutal entre ~2.180 e ~77. Não é bug da coleta — é o que o Waze
entrega.

**Só existem três janelas.** `ALL_TIME`, `PAST_WEEK` e `PAST_MONTH`. Qualquer
outro valor de `lookbackPeriod` — `PAST_YEAR`, `LAST_7_DAYS`, ou lixo puro —
volta com status 200 e o payload de `ALL_TIME`, sem erro nenhum. O script fixa
o enum do lado do cliente para essa armadilha não passar batida.

Dava para contornar tudo isso guardando snapshots diários e comparando: um diff
de dois `ALL_TIME` com um mês de distância pegaria os ~2.180 que editaram, não
77, e permitiria qualquer janela. Fica registrado como caminho caso um dia haja
onde armazenar — o histórico do git tem o coletor com snapshot e diff, e o
suporte a outros países, removidos daqui por estarem fora do escopo atual.

## Notas

- Cookies são credencial de sessão. O `.gitignore` bloqueia `cookies*.txt`,
  `*.har` e `.env`; melhor manter assim.
- O script limita a ~3 req/s em 4 workers e faz backoff em falha. Não observei
  rate limiting do lado do Waze, mas a infraestrutura não é nossa.
- `/_user/api/user` e `/il-UsersProfile/app/userInfo` devolvem PII real **do
  próprio chamador** — nome completo, e-mail, cidade, última coordenada. Ambos
  ignoram o parâmetro `userId`, então não servem para consultar terceiros, e
  nada dali entra no placar.
- `level` some do registro de quem nunca editou. Não assuma que a chave existe.

O contrato completo da API, com as medições, está em
[`docs/api-recon.md`](docs/api-recon.md).
