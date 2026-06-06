# Bot de Ofertas Telegram com Links de Afiliado

Bot em Python para monitorar grupos de ofertas no Telegram, identificar links de produtos e repostar no grupo destino com links de afiliado.

O projeto automatiza principalmente ofertas do Mercado Livre. Ele pega links recebidos em grupos, abre o link afiliado original, encontra a URL real do produto sem afiliado, gera um novo link pelo Link Builder do Mercado Livre usando a sua conta e reposta a mensagem.

## O que ele faz

- Monitora grupos/canais do Telegram usando Telethon.
- Detecta links em mensagens recebidas.
- Resolve encurtadores como `https://meli.la/...`.
- Para Mercado Livre:
  - abre o link recebido com Playwright;
  - clica em `Ir para produto`;
  - captura a URL real do produto;
  - remove parametros de rastreamento/afiliado;
  - envia a URL limpa para a API do Link Builder;
  - recebe o link afiliado da sua conta;
  - reposta no grupo destino sem preview automatico.
- Para Amazon:
  - remove tag antiga;
  - aplica a tag configurada no `.env`.

## Fluxo do Mercado Livre

```text
Mensagem recebida no Telegram
-> Extrai URL
-> Resolve meli.la
-> Abre link do Mercado Livre no navegador
-> Clica em "Ir para produto"
-> Captura URL normal do produto
-> Limpa parametros de afiliado/rastreamento
-> Envia para a API createLink
-> Recebe link afiliado da conta configurada
-> Reposta no Telegram
```

O link final do Mercado Livre pode continuar no formato:

```text
https://www.mercadolivre.com.br/social/seuusuario?...
```

Isso pode estar correto. O importante e que o `ref` seja gerado pela API do Mercado Livre depois que o bot encontrou a URL real do produto.

## Requisitos

- Python 3.10+
- Conta Telegram para usar com Telethon
- Conta de afiliado Mercado Livre
- Playwright com navegador Chromium instalado

Dependencias do projeto:

```text
telethon
httpx
python-dotenv
playwright
```

## Instalacao

Instale as dependencias:

```bash
pip install -r requirements.txt
```

Instale o navegador do Playwright:

```bash
playwright install chromium
```

## Configuracao

Copie `.env.example` para `.env` e preencha os valores:

```bash
cp .env.example .env
```

No Windows, voce tambem pode duplicar o arquivo manualmente e renomear para `.env`.

### Telegram

Pegue `API_ID` e `API_HASH` em:

```text
https://my.telegram.org/apps
```

`SOURCE_GROUPS` recebe os grupos/canais monitorados separados por virgula:

```env
SOURCE_GROUPS=grupo1,grupo2,https://t.me/+convite
```

`TARGET_GROUP` e o grupo onde o bot vai repostar.

### Mercado Livre

`ML_AFFILIATE_WORD` e sua tag/nome de afiliado:

```env
ML_AFFILIATE_WORD=valneymaia
```

`ML_AFFILIATE_ID` e o identificador usado pelo Mercado Livre nos links.

`ML_CREATE_LINK_COOKIE` e `ML_CSRF_TOKEN` vem da sua sessao logada no Mercado Livre.

Para pegar:

1. Acesse o Mercado Livre logado.
2. Abra o Link Builder:
   ```text
   https://www.mercadolivre.com.br/afiliados/linkbuilder
   ```
3. Abra o DevTools do navegador (`F12`).
4. Va em `Network` / `Rede`.
5. Gere um link manualmente.
6. Clique na requisicao `createLink`.
7. Em `Request Headers`, copie:
   - `cookie` inteiro para `ML_CREATE_LINK_COOKIE`;
   - `x-csrf-token` para `ML_CSRF_TOKEN`.

Esses valores sao sensiveis e expiram. Se o bot retornar erro `401`, `403` ou parar de gerar links, atualize cookie/token.

### Amazon

Configure sua tag:

```env
AMAZON_AFFILIATE_TAG=suatag-20
```

## Como rodar

```bash
python bot.py
```

Na primeira execucao, o Telethon pode pedir login da conta Telegram.

## Logs uteis

Quando o bot abre o link do Mercado Livre:

```text
[MLC] Abrindo link ML no navegador para pegar produto sem afiliado...
```

Quando captura a URL real:

```text
[MLC] URL bruta capturada pelo navegador: ...
[MLC] URL limpa capturada pelo navegador: ...
```

Quando envia para o Link Builder:

```text
[MLC] Enviando produto limpo ao Link Builder: ...
```

Quando gera o link:

```text
[ML ] API ML gerou link social afiliado: ...
```

Quando reposta:

```text
[+] Repostado!
```

## Seguranca

Nao suba estes arquivos para o GitHub:

- `.env`
- `*.session`
- `*.session-journal`

O `.env` contem credenciais do Telegram e sessao/cookie do Mercado Livre. Os arquivos `.session` contem a sessao autenticada do Telethon.

## Estrutura

```text
bot.py              Bot principal
config.py           Leitura das variaveis do .env
requirements.txt    Dependencias Python
README.md           Documentacao do projeto
.env.example        Exemplo seguro de configuracao
.gitignore          Arquivos que nao devem ir para o GitHub
```

## Observacoes

- O preview automatico de links do Telegram esta desativado para evitar card extra embaixo da mensagem.
- O Mercado Livre pode mudar a pagina ou a API interna, entao o seletor do botao `Ir para produto` pode precisar de ajuste futuramente.
- Cookie e CSRF do Mercado Livre podem expirar e precisar ser atualizados.
