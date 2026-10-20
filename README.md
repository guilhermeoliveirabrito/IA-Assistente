# Assistente pessoal automático (emails + agenda)

Roda no seu computador, sozinho, em segundo plano. Custo: zero (Gmail API, Calendar API e Gemini na camada gratuita).

## O que ele faz
- A cada 15 min lê os emails novos e classifica: importante / normal / newsletter / spam.
- Todo dia às 08:00 gera um resumo do que realmente importa e quais emails pedem resposta.
- Todo dia às 07:30 analisa sua agenda e sugere ajustes (conflitos, dias lotados, janelas de foco).
- Spam: por padrão ele **só sugere**; você aprova com `python main.py aprovar`. Tudo vai para a lixeira (recuperável 30 dias), nunca é apagado para sempre.

## O que ele ainda NÃO faz
- WhatsApp (deixamos para a etapa 2).
- Alterar sua agenda (por segurança, só leitura por enquanto).
- Responder emails sozinho.

## Instalação (uns 15 minutos)

### 1. Python e dependências
Instale o Python 3.10+ e rode, dentro desta pasta:
```
pip install -r requirements.txt
```

### 2. Liberar acesso ao Gmail e à Agenda (Google Cloud, grátis)
1. Acesse https://console.cloud.google.com e crie um projeto (ex.: "assistente").
2. Em "APIs e serviços" > "Biblioteca", ative **Gmail API** e **Google Calendar API**.
3. Em "Tela de consentimento OAuth": tipo **Externo**, preencha o básico e, em "Usuários de teste", adicione o seu próprio email.
4. Em "Credenciais" > "Criar credenciais" > **ID do cliente OAuth** > tipo **App para computador**.
5. Baixe o JSON e salve nesta pasta com o nome `credentials.json`.
6. Rode `python main.py setup`. O navegador abre, você faz login e autoriza (pode aparecer um aviso de "app não verificado": é o seu próprio app, clique em Avançado > continuar).

> Dica: no modo "teste" o login do Google expira a cada 7 dias. Se isso incomodar, na tela de consentimento clique em "Publicar app" (continua só para você).

### 3. Chave do Gemini (grátis)
1. Acesse https://aistudio.google.com/apikey e crie uma chave.
2. Defina como variável de ambiente:
   - Windows (PowerShell): `setx GEMINI_API_KEY "sua_chave"` (feche e abra o terminal)
   - Mac/Linux: `export GEMINI_API_KEY="sua_chave"` (ponha no ~/.bashrc ou ~/.zshrc)

### 4. Teste
```
python main.py triagem     # classifica emails agora
python main.py resumo      # resumo das últimas 24h
python main.py agenda      # análise da agenda
python main.py aprovar     # revisa o que a IA quer mandar para a lixeira
```

### 5. Deixar rodando sozinho
```
python main.py rodar
```
Deixe o terminal aberto. Para iniciar junto com o computador:
- Windows: Agendador de Tarefas > "Ao fazer logon" > executar `python main.py rodar` nesta pasta.
- Mac: crie um LaunchAgent (me peça que eu escrevo).
- Linux: um serviço `systemd` (me peça que eu escrevo).

Resumos e análises ficam salvos em `data/` além de aparecerem no terminal.

## Ajustando
Tudo está em `config.yaml`: critérios de "importante", remetentes VIP, horários, preferências de agenda e modo de spam. Quando confiar na triagem, mude `spam.modo` para `automatico`.

## Segurança
- `credentials.json` e `token.json` dão acesso ao seu email. Nunca compartilhe.
- A IA trata o texto dos emails como dado, não como ordem, para reduzir o risco de alguém "mandar" o assistente fazer algo por email.
- Limite gratuito do Gemini: se estourar, a rodada falha e tenta de novo na próxima.

## Próximas etapas
1. Rascunhos de resposta para emails que pedem resposta (você aprova antes de enviar).
2. WhatsApp com aprovação (API oficial da Meta ou biblioteca não oficial, com risco de banimento).
3. Criar blocos de foco na agenda, com sua aprovação.
4. Tarefas e projetos em segundo plano.
