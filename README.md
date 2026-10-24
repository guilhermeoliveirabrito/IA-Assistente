# IA-Assistente

Um assistente pessoal de IA que roda no **seu próprio computador**, como um aplicativo com janela própria. Ele conversa com você, lê seus e-mails e agenda, entende PDFs, imagens e textos, controla o PC (abrir programas, tocar música, digitar e clicar) e trabalha em projetos **sozinho, em segundo plano**, enquanto você está fora, e você acompanha tudo pelo computador ou pelo celular.

Custo: **zero** (Gemini na camada gratuita, Gmail e Google Agenda, Spotify com a sua conta). Projeto open source em português, licença MIT.

> Seus dados ficam na sua máquina. Só os trechos necessários vão para a API do Gemini para a IA responder.

## O que ele faz

| Recurso | Como funciona |
|---|---|
| **App com janela própria** | Interface com tema escuro, claro ou automático, busca nas conversas, exportar para Markdown, atalhos de teclado (`?` mostra a lista), respostas com tabelas, listas e código formatados, indicador de "pensando", voz opcional (falar em vez de digitar; ler respostas em voz alta) |
| **Agentes especializados** | Escolha no chat um especialista (Programador, Pesquisador, Redator, Organizador, Analista, Professor, Operador do PC), crie os seus ou use a **Mesa de debate**: um agente defende, outro contesta e um juiz decide |
| **Automação** | Aba com tudo o que ele confere sozinho (e-mails, agenda, resumo e encomendas): quando roda de novo, o que a última achou e botão "Verificar agora". O medidor (e a lateral) mostram **quanto falta para a próxima checagem de e-mail**, a agenda e as encomendas, o que a última encontrou, e há o botão "Verificar agora" |
| **Medidor por modelo** | Mostra **qual Gemini está em uso**, quanto cada modelo já gastou hoje, quando a cota renova e avisa quando o app troca de modelo e por quê |
| **Arquivos e imagens** | Arraste ou cole imagens, PDFs, Word e arquivos de texto/código no chat |
| **Início** | Tela inicial com o **resumo do dia** (agenda de hoje, e-mails importantes, encomendas e lembretes), gerado sozinho de manhã (08:00 por padrão, também avisa no celular) ou na hora pelo botão |
| **Lembretes e alarmes** | "Me lembra às 18h de ligar pro João", "daqui a 20 minutos", "todo dia útil às 8h". Avisa no PC (banner + som, mesmo com a janela na bandeja) **e no celular**. Alarme toca até você dispensar ou adiar. Também pode **mandar o assistente fazer algo** na hora marcada (ex.: resumir e-mails todo dia) |
| **Internet** | Pesquisa na web com as fontes (pesquisa do Google via Gemini; se falhar, DuckDuckGo) e leitura de páginas públicas, protegida contra acesso à sua rede local |
| **Vários provedores de IA** | Gemini primeiro; se ele acabar a cota, cair ou ficar sem chave, o app passa sozinho para Groq, Cerebras, OpenRouter, Mistral, GitHub Models, NVIDIA, DeepSeek, OpenAI, Claude ou um modelo local no Ollama (quem tiver chave). Tudo em Ajustes › Provedores de IA |
| **E-mails** | Triagem a cada 15 min (importante / normal / newsletter / spam), resumo diário. Pelo chat: buscar e ler e-mails, **criar rascunhos e respostas** no seu Gmail, marcar como lido, arquivar. **Enviar** de verdade só se você liberar em Ajustes. Spam só vai para a lixeira com a sua aprovação (por padrão) e nunca é apagado para sempre |
| **Agenda** | Aponta conflitos, dias lotados e janelas livres; **cria, altera e apaga eventos** ("marque dentista amanhã às 15h") |
| **Arquivos e área de transferência** | Grava notas, listas e resumos (texto/dados, nunca programas) na pasta de saída, com chave para pedir ou não permissão; lê e escreve na área de transferência para ajudar no controle do PC |
| **Ativação por voz** | Diga **"ei assistente"** e ele começa a ouvir o seu comando na hora, como a Siri/"Ok Google", e responde falando (veja abaixo) |
| **Encomendas** | Informe o código de rastreio (na aba ou pelo chat) e ele acompanha sozinho, mostra o histórico e **avisa quando algo mudar** ou quando achar (ou não) o pacote |
| **Controle do PC** | Abre apps e sites, controla mídia, vê a tela, digita, clica. **Cada ação de risco pede a sua permissão** |
| **Spotify** | "Toque tal música" pela API oficial (precisa de Premium) |
| **Tarefas autônomas** | Você descreve um trabalho; ele faz um plano, cria o projeto numa pasta própria, escreve código, roda comandos e (se você permitir) envia ao GitHub. Orçamento por tarefa, pausa quando a cota acaba e **continua sozinho quando ela renova** |
| **Histórico** | Registro do que ele planejou e fez, que **se apaga sozinho** depois de alguns dias |
| **Memória editável** | Arquivos `.md` que você edita pelo app; entram em todas as respostas |
| **Celular** | Aprove pedidos e mande tarefas do iPhone (veja abaixo) |

Ainda não faz: WhatsApp (adiado de propósito; as opções não oficiais podem banir o número) e rodar com o computador desligado.

## Instalação

### 1. Python e dependências
Instale o Python 3.10+ e, na pasta do projeto:
```
python -m venv .venv
.venv\Scripts\activate          # Windows  (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

### 2. Chave do Gemini (grátis)
Crie uma chave em https://aistudio.google.com/apikey, copie `.env.example` para `.env` e cole lá.

### 3. Abrir o app
```
python app.py
```
No Windows, também dá para dar dois cliques em **Abrir Assistente.bat** (sem janela preta). Sem o `pywebview` o app abre no navegador.

Pronto: já dá para conversar, mandar arquivos e imagens e criar tarefas. O resto é opcional:

### 4. Gmail e Agenda (opcional)
1. Em https://console.cloud.google.com crie um projeto e ative a **Gmail API** e a **Google Calendar API**.
2. Em "Tela de consentimento OAuth": tipo **Externo** e, em "Usuários de teste", adicione o seu e-mail.
3. Em "Credenciais" crie um **ID do cliente OAuth** do tipo **App para computador**, baixe o JSON e salve como `credentials.json` na pasta do projeto.
4. Abra o app, vá em **Ajustes › Gmail e Agenda** e clique em **Conectar Google**. Autorize no navegador que abrir (o aviso de "app não verificado" é o seu próprio app: Avançado > continuar). Se preferir o terminal: `python main.py setup`.

Com o login feito, o app liga sozinho a rotina de e-mails e agenda em segundo plano, e você também pode pedir no chat ("resuma meus e-mails"). Para revisar o que a IA quer mandar para a lixeira: `python main.py aprovar`.

### 5. Spotify (opcional, precisa de Premium)
1. Em https://developer.spotify.com/dashboard crie um app.
2. Em "Redirect URIs" cadastre exatamente `http://127.0.0.1:8888/callback`.
3. Coloque o *Client ID* em `SPOTIFY_CLIENT_ID` no `.env` e reabra o app.
4. Em **Ajustes › Spotify**, clique em *Conectar* e autorize.

### 6. Rastreio de encomendas (opcional)
Os Correios fecharam a consulta pública e a API oficial exige contrato com CNPJ, então o app usa o **17TRACK** (reconhece Correios e centenas de transportadoras):
1. Crie uma conta grátis em `17track.net`, entre na área da **API** e copie a *chave de acesso* (Security Key).
2. No arquivo `.env`, acrescente `TRACK17_KEY=sua_chave` e reabra o app.
3. Na aba **Encomendas**, cole o código (ou peça no chat: "acompanhe a encomenda AA123456789BR").

Ele consulta a cada 60 min (`rastreio.verificar_a_cada_minutos`, mínimo 15) só o que ainda não foi entregue, e a contagem para a próxima consulta aparece no medidor. Você é avisado na aba (com um número na barra lateral), no app e, se ativou os avisos, no celular. Se o código ainda não existir no sistema da transportadora, ele diz que **não encontrou** e continua tentando.

Limites honestos: pelas regras do 17TRACK, contas novas ganham uma cota única de **200 códigos gratuitos** (cada código novo gasta 1; consultar de novo não gasta), e a integração foi escrita pela documentação e testada só com respostas simuladas — se a sua chave se comportar diferente, o app mostra o erro na própria encomenda. Sem a chave, os códigos ficam guardados e há o link para consultar no site.

### 7. Outros provedores de IA (opcional)
O Gemini continua sendo o principal. Para o app não parar quando a cota dele acabar, abra **Ajustes › Provedores de IA**, pegue uma chave grátis em um ou mais sites (cada linha tem o link “Pegar chave”), cole, clique em **Salvar** e depois **Testar**. As chaves ficam só no seu `.env`. Marque quem pode ser usado e use as setas para mudar a ordem da fila. Com o **Ollama** (https://ollama.com), um modelo roda no seu PC, sem limite e sem internet: instale, rode `ollama pull llama3.2` e marque “Ollama (local)”.

Observações honestas: os nomes de modelo são padrões e podem mudar nos provedores (edite o campo do modelo se um deixar de existir); os limites grátis também mudam; Groq, Cerebras, OpenRouter e NVIDIA padrão não enxergam imagens, então o controle do PC por tela só cai em provedores que veem imagens (Mistral, GitHub Models, OpenAI, Claude) e, se não houver nenhum, espera o Gemini voltar.

### 8. Projetos e GitHub (opcional)
Em **Ajustes › Projetos**, escolha a pasta onde ele cria os projetos e liste os repositórios (`usuario/repo`) em que ele **pode** enviar código. Fora dessa lista ele nunca faz push. O envio usa o `git` e as credenciais que já estão no seu computador.

## Agentes especializados e mesa de debate

Na caixa de mensagem do chat, o botão com o nome do agente (começa em **✨ Geral**) abre a lista de especialistas. A escolha vale para aquela conversa e dá para trocar a qualquer momento (menos no meio de uma resposta).

| Agente | Para que serve | Ferramentas que perde |
|---|---|---|
| ✨ **Geral** | Faz de tudo (padrão) | nenhuma |
| 💻 **Programador** | Escrever, revisar e depurar código; projetos e git | teclado e mouse |
| 🔎 **Pesquisador** | Pesquisar na internet, conferir fontes e citar | PC, comandos, escrita em projetos |
| ✍️ **Redator** | Escrever, revisar, resumir e traduzir | PC, comandos, escrita em projetos |
| 🗓️ **Organizador** | Agenda, e-mails, lembretes e encomendas | PC, comandos, escrita em projetos |
| 📊 **Analista** | Contas, números, planilhas e finanças pessoais | teclado e mouse |
| 🎓 **Professor** | Explicar com exemplos e exercícios | PC, comandos, escrita em projetos |
| 🖱️ **Operador do PC** | Usar o computador por você | nenhuma |
| ⚖️ **Mesa de debate** | Ver abaixo | (não usa ferramentas) |

Em **Criar o meu agente** você escreve o nome, um ícone e as instruções; ele fica salvo em `data/agentes.json`. Agentes seus não recebem teclado e mouse. As permissões (o que pede aprovação) são as mesmas para todos.

**Mesa de debate.** Você descreve uma ideia ou decisão ("devo trocar de emprego?", "vale migrar o projeto para Rust?"). Um **defensor** e um **opositor** montam seus argumentos sem ver um ao outro, respondem um ao outro (réplica) e um **juiz** imparcial decide. Você recebe **só o parecer do juiz**: veredito, razões, ressalvas e próximo passo. O agente Geral também pode abrir um debate sozinho (ferramenta `debater`) quando você pedir "prós e contras". Cada debate usa 5 requisições da cota do dia (3 + 2 por rodada de réplica); ajuste `debate.rodadas` no `config.yaml` (0 a 2). Os argumentos dos dois lados não são mostrados nem guardados na conversa.

**Comandos com `/` no chat.** Digite `/` e escolha: `/debate tema` (abre a mesa de debate só para aquela mensagem, em qualquer agente), `/agente` ou `/agente programador` (troca o especialista), `/pesquisar`, `/lembrete`, `/lembrar` (guarda na memória), `/resumo` (resumo do dia) e `/novo`. Tab ou Enter completa o primeiro da lista.

**Tentar de novo.** O botão de seta na última resposta descarta aquela resposta e gera outra para o mesmo pedido.

**Nas tarefas autônomas** você também escolhe o agente (menos a mesa de debate): ele define o jeito de trabalhar e as ferramentas que a tarefa recebe.

## Lembretes, resumo do dia e arquivos

- **Lembretes** (aba Lembretes, chat ou voz): único ou recorrente (todo dia, dias úteis, toda semana, todo mês, a cada N minutos); alarme toca até dispensar; botões de soneca (+5, +10, +60 min). O aviso do celular usa o ntfy (Ajustes › Avisos no celular). Se o app ficou fechado, lembretes únicos atrasados disparam ao abrir; recorrentes muito atrasados só são reagendados. Os horários são os do relógio do computador.
- **Resumo do dia**: em `config.yaml › automatico` (`resumo_do_dia`, `resumo_do_dia_as`) ou em Ajustes. Sem Google ele ainda mostra encomendas e lembretes.
- **Agenda e e-mail**: quem já tinha conectado o Google só tem permissão de **leitura** na agenda. Em Ajustes › Gmail e Agenda clique em **Reconectar para permitir criar eventos**. Enviar e-mail está **desligado** por padrão: ele cria o rascunho e você envia; ligue a chave em Ajustes se quiser que ele envie sozinho.
- **Arquivos que ele cria**: ficam em `arquivos.pasta_de_saida` (padrão `~/Documents/Assistente`). Ao substituir um arquivo, guarda um `.bak`. A chave “Gravar arquivos sem pedir permissão” (Ajustes › Arquivos que ele cria) vale quando o modo autônomo está desligado.

## Ativação por voz ("ei assistente")

Ligue em **Ajustes › Ativação por voz**: instale as dependências (`pip install -r requirements.txt`), clique em *Baixar modelo de voz* (≈ 30 MB, uma vez) e ative. Aí é só falar **"ei assistente, abre o bloco de notas"** (ou falar a frase, esperar o bipe e dizer o comando). Ele grava até você ficar em silêncio, transcreve, executa e **lê a resposta curta em voz alta** (voz do Windows). Os pedidos por voz continuam a mesma conversa por voz por até 30 minutos.

Como funciona: um reconhecedor **offline** (Vosk) só procura a frase de chamada, no seu computador; o resto que você fala é descartado na hora. Só o trecho **depois** da chamada é transcrito, pelo Gemini (acerta mais; gasta 1 requisição) ou localmente (grátis, sem internet, erra mais; escolha em Ajustes). A escuta fica em pausa enquanto ele fala, para não ouvir a si mesmo.

Com a voz ligada, **fechar a janela só a esconde** e o app continua ouvindo (ícone na bandeja do Windows: *Abrir* / *Sair*; precisa do `pystray`, que está no `requirements.txt`). Sem o ícone da bandeja, fechar a janela encerra o app.

Limites honestos:
- **"Ok Google" e "Siri" provavelmente não funcionam**: o modelo de voz só entende palavras do português; o app testa a frase ao ligar e avisa quais palavras não conhece. O padrão **"ei assistente"** foi escolhido por existir no vocabulário; frases de 2 a 3 palavras funcionam melhor.
- Sem a Siri/Google, não existe hardware dedicado: ruído alto, TV ligada ou microfone ruim causam falhas e ativações falsas. Fones ajudam.
- Bipe e resposta falada só no Windows. O microfone precisa estar liberado em *Configurações › Privacidade › Microfone*.
- Esta parte depende de microfone e foi testada **só com áudio simulado**; se algo se comportar diferente no seu PC, me conte.

## Como ele enxerga e controla o mouse

Para clicar, ele recebe uma foto da tela com uma **grade de números de 0 a 1000** (a escala em que o Gemini enxerga melhor, independente da resolução e do zoom do Windows), mira no alvo e, depois de cada clique, tecla ou texto, recebe uma foto nova mostrando **onde clicou** (círculo vermelho). Para alvos pequenos ele amplia uma região antes de clicar. Sempre que dá, ele prefere atalhos de teclado e abrir programas e sites direto, que são mais confiáveis que clicar.

Enquanto usa tela, teclado e mouse ele **minimiza a janela do assistente** (para não digitar nela mesma) e a restaura ao terminar. Dá para desligar em Ajustes › Permissões. Se mover o mouse para um canto da tela, tudo é interrompido (trava de segurança do pyautogui), e o botão Parar do app também interrompe na hora.

### Precisão no controle do PC
Além da grade de coordenadas, no **Windows** o assistente usa o que o próprio sistema sabe sobre a janela (instale com `pip install -r requirements.txt`, que inclui `uiautomation`):
- **Elementos numerados** (`listar_elementos` + `clicar_elemento`): os botões, campos e links da janela ativa saem numerados em caixas rosa na captura, e ele clica pelo número, no centro exato, sem adivinhar x e y. Se a janela não expõe elementos (jogos, apps customizados), ele volta para a grade.
- **Janelas** (`listar_janelas` + `focar_janela`): traz um programa para frente pelo título, esperando ele abrir, em vez de alt+tab no escuro.
- **Espera a tela estabilizar** antes de tirar a foto de resultado (em vez de um atraso fixo): fica rápido quando nada muda e paciente quando uma página carrega.
- **Detecta ação sem efeito**: se a tela não mudou nada depois de um clique ou tecla, o modelo é avisado para não repetir igual e mudar de alvo ou método.
Sem o pacote (ou fora do Windows) essas ferramentas simplesmente não aparecem e tudo segue pela grade.

### Velocidade no controle do PC
Cada passo (olhar a tela, escolher o clique) é uma chamada ao Gemini, então o tempo entre um passo e outro é quase todo o tempo "pensando" do modelo. Para acelerar:
- **Raciocínio mínimo no controle do PC** (`ia.raciocinio_pc`, padrão `minimal`; só modelos Gemini 3). Nas conversas normais fica em `auto` (`ia.raciocinio`). Se a API recusar o parâmetro para algum modelo, o app tenta outra grafia e, por fim, segue sem ele.
- **Várias ações por passo**: o modelo é orientado a pedir clique + digitar + enter de uma vez; só a última ação tira a foto da tela, e só a foto mais recente é enviada.
- **Modelos rápidos para o PC** (`ia.modelos_pc`, padrão os dois Lite, com cota de 500/dia): depois que ele começa a mexer no PC, esses modelos entram na frente. Se achar que o Lite erra demais os cliques, deixe `modelos_pc: []` para usar sempre o principal.
- **Resposta travada é abandonada em 45 s** no controle do PC (o app tenta o próximo modelo) em vez de esperar 2 minutos.
- **Sem desperdiçar chamadas**: se, pela contagem do app, um modelo já atingiu o limite por minuto ou por dia, a chamada vai direto ao próximo (com os limites reais do seu painel, os modelos de 5 por minuto passam a vez rápido para os de 15).
- **Medidor de tempo**: enquanto pensa, a tela mostra os segundos ("Pensando… · 12 s", em amarelo após 30 s) e passos lentos ficam no Histórico dizendo se a demora foi do modelo ou das ações.

## Como funcionam as tarefas autônomas

Em **Tarefas › Nova tarefa** você escolhe o que ele pode fazer sozinho:

- **Só leitura**: lê arquivos, e-mails e agenda, mexe na memória e na música.
- **Projeto**: também cria arquivos, roda comandos de desenvolvimento permitidos, abre apps e envia ao GitHub (só para os repositórios que você listou).
- **Controle total**: também usa tela, teclado e mouse (a janela do app se esconde enquanto isso).

(Com o modo autônomo ligado, que é o padrão, essa escolha some: ele já pode tudo isso.)

Por padrão o app roda em **modo autônomo**: ele usa o PC (abrir apps, tela, teclado, mouse, comandos) **sem pedir permissão** e você vê tudo depois no **Histórico**. Ele só para e pergunta se uma ação for **contra uma regra que você escreveu** em Memória › Regras (por exemplo, "nunca apague fotos"). Para voltar a ser perguntado a cada ação, desligue o modo autônomo em Ajustes › Permissões; aí valem os perfis acima, e ações de risco alto (comandos, tela/teclado/mouse, `git push`) pedem aprovação, no app ou por aviso no celular.

As travas técnicas continuam sempre ligadas, no modo autônomo também: comandos só rodam na pasta de projetos e só com programas da lista permitida, e o `git push` só vai para os repositórios que você listou. Elas bloqueiam em vez de perguntar. Cada tarefa tem um **orçamento de requisições** para não gastar a cota do dia inteira; ao acabar, ela pausa e espera você liberar mais.

### E se a cota gratuita acabar?
- O app tenta primeiro os **modelos reserva** (a cota gratuita é separada por modelo).
- Se todos acabarem, as tarefas **pausam** (nada se perde) e **retomam sozinhas** logo depois da renovação diária (por padrão, meia-noite no horário do Pacífico; o app mostra a hora no seu fuso).
- O chat avisa que a cota acabou e quando volta. Se o Google der só um limite por minuto, o app espera alguns segundos e tenta de novo.

**Expectativa honesta:** o plano gratuito dá conta de **uma tarefa de cada vez**, de tamanho pequeno a médio (um site simples, um script, organizar arquivos, pesquisar e resumir). Trabalho longo de programação, com muitas idas e vindas, consome a cota do dia rápido e termina em vários dias. Vários agentes trabalhando em paralelo ("empresa de agentes") **não cabem** no plano gratuito. Os limites do Google mudam; confira os seus em https://aistudio.google.com/rate-limit e ajuste em **Ajustes › Limites da cota**. 

**Como o medidor funciona (e o que ele não consegue):** o Google não tem nenhuma chamada que informe a cota restante. Então o app conta **cada requisição e cada token que ele mesmo envia a cada modelo** (contagem exata do que passa pelo app) e usa o que o Google diz quando **recusa** uma chamada (erro 429): aí o modelo é marcado como esgotado e o app aprende o **limite real** dele. O que o app não vê é uso da mesma chave fora dele (outro programa, o AI Studio). Para esse caso, em cada modelo há o botão **Ajustar com o painel do Google**: você digita o número que o painel mostra e o app soma a diferença. Limites conhecidos podem ser escritos em Ajustes › Limites de cada modelo.

## Usar pelo celular (iPhone)

O app é uma página servida pelo seu PC. Para o celular alcançá-la:

1. **Ajustes › Usar pelo celular** > ligue *Permitir acesso pela rede* e reabra o app. Ele mostra um **código de acesso** e os endereços.
2. No iPhone, na **mesma rede Wi-Fi**, abra o endereço no Safari. Depois: *Compartilhar › Adicionar à Tela de Início* e ele vira um ícone, como um app.
3. **Fora de casa**, instale o **Tailscale** (grátis) no PC e no iPhone e abra o endereço do Tailscale. É uma rede privada entre os seus aparelhos: não abra a porta do roteador para a internet.
4. **Avisos**: em **Ajustes › Avisos no celular** clique em *Ativar avisos*, instale o app gratuito **ntfy** no iPhone e assine o tópico mostrado. Você recebe um aviso quando ele precisar de aprovação, terminar, pausar ou falhar, e responde pelo app.

Observações: o computador precisa estar **ligado, com o app aberto e conectado à internet**. O microfone no iPhone só funciona com HTTPS (por exemplo, o endereço HTTPS do Tailscale); digitar funciona sempre.

## Memória e conversas longas

- A **memória** são arquivos de texto (`perfil.md`, `regras.md`, `notas.md` e outros) que você edita em **Memória**. O assistente também anota ali quando você pede "lembre que...".
- Conversas muito longas pesam e gastam cota. Por isso, quando uma conversa passa de um certo tamanho, o começo é **resumido automaticamente** e fica só o resumo mais as mensagens recentes. Imagens antigas saem do contexto.
- Em qualquer conversa, menu (⋮) › **Resumir e continuar** cria uma **conversa nova que começa de um resumo** da anterior, para recomeçar leve sem perder o fio.
- As tarefas também resumem o próprio andamento entre uma etapa e outra.

## Segurança

- O app só aceita conexões com o **código de acesso** (guardado em `data/access_token.txt`). No modo "local" só o próprio PC conecta; ainda há proteção contra sites maliciosos abertos no seu navegador e limite de tentativas erradas.
- `credentials.json`, `token.json`, `.env`, `data/` e `memory/` estão no `.gitignore` e **nunca** devem ser enviados ao Git.
- E-mails, arquivos e páginas lidos são tratados como **dados, nunca como ordens**, para reduzir o risco de alguém "mandar" o assistente fazer algo escondido num e-mail ou documento. Nenhuma defesa é perfeita; por isso o que é arriscado exige a sua aprovação.
- Comandos só rodam dentro da pasta de projetos, sem *shell*, com lista de programas permitidos. O `git push` só vai para repositórios que você listou.
- Quem tem o código de acesso controla o assistente. Trate-o como uma senha.

## Estrutura

```
app.py                       atalho que abre o app (janela própria)
main.py                      atalho dos comandos de terminal (setup, triagem, memória...)
config.yaml                  configurações (o que muda no app fica em data/settings.json)
web/                         interface (HTML/CSS/JS puro, sem build)
memory_example/              modelos das notas de memória
tests/                       testes automáticos (não chamam Gemini, Google nem o Windows)
assistente/
  app.py  server.py  cli.py  janela/bandeja, servidor local + API da interface, comandos de terminal
  nucleo/                    base do app, sem depender dos outros pacotes
    settings  permissions  storage  usage  bus  memory  attachments  activity  workspace
  ia/                        tudo que fala com modelos de IA
    llm        ponto único de IA: Gemini primeiro, depois os outros provedores
    gemini  providers        clientes (Gemini; OpenAI-compatíveis, Claude e Ollama)
    agent  agent_tools       laço do agente (pensa, usa ferramentas, pede permissão) e as ferramentas
    agentes  debate         agentes especializados e a mesa de debate (defensor, opositor e juiz)
    ai  chat  chatsvc  context   perguntas simples, conversa de terminal, conversas/anexos/aprovações, resumo de contexto
  integracoes/               serviços externos
    google_auth  google_actions  gmail_tools  agenda  triage   Google (login, agenda, e-mail, triagem)
    spotify_control  notify  web_tools                          Spotify, avisos no celular (ntfy), internet
  pc/                        o computador
    pc_control  uia  files  wake    tela/teclado/mouse, janelas (Windows), arquivos, voz
  servicos/                  rotinas em segundo plano
    tasks  tracking  reminders  briefing  automation
```

Regras simples: `nucleo` não importa os outros pacotes (única exceção: `settings` lê a lista de provedores); `ia`, `integracoes`, `pc` e `servicos` podem usar o `nucleo`; só `server`, `app` e `cli` juntam tudo.

## Testes e qualidade
```
python -m unittest discover -s tests -t .
node web/tests/md.test.js
ruff check .            # estilo e código morto (configurado em pyproject.toml)
```

## Contribuindo
O GitHub roda os testes e o `ruff` a cada envio (`.github/workflows/ci.yml`).

Os commits seguem o padrão *Conventional Commits*: `feat:` (funcionalidade nova), `fix:` (correção), `docs:`, `refactor:`, `perf:`, `test:`, `style:` e `chore:`, com uma frase curta no imperativo.

## Roadmap
1. WhatsApp com aprovação (via API oficial)
2. Agentes que trabalham em equipe nas tarefas autônomas (hoje a mesa de debate já combina vários agentes no chat, e cada tarefa pode ter um especialista)
