#!/bin/bash

# Cores para formatação de output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # Sem Cor

echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}    Instalador Interativo: supportFAQagent    ${NC}"
echo -e "${GREEN}=============================================${NC}"

# 1. Detecção do Sistema Operacional e Interpretador Python
IS_WINDOWS=false
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    IS_WINDOWS=true
    echo -e "${YELLOW}Ambiente Windows detectado (via Git Bash/MSYS).${NC}"
else
    echo -e "${YELLOW}Ambiente Unix/Linux detectado.${NC}"
fi

# Detectar executável do Python
if command -v python3 &>/dev/null; then
    PYTHON_EXE="python3"
elif command -v python &>/dev/null; then
    PYTHON_EXE="python"
else
    echo -e "${RED}Erro: Python não encontrado. Por favor, instale o Python 3.11+.${NC}"
    exit 1
fi

# Verificar versão do Python (mínimo 3.11)
$PYTHON_EXE -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if [ $? -ne 0 ]; then
    python_ver=$($PYTHON_EXE -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    echo -e "${RED}Erro: A versão do Python detectada é $python_ver. O projeto exige Python 3.11+.${NC}"
    exit 1
fi
echo -e "${GREEN}✔ Python 3.11+ detectado com sucesso.${NC}"

# Verificar Git
if command -v git &>/dev/null; then
    echo -e "${GREEN}✔ Git detectado com sucesso.${NC}"
else
    echo -e "${RED}Erro: Git não está instalado ou não está no PATH.${NC}"
    exit 1
fi

# Verificar Docker (opcional, mas recomendado)
HAS_DOCKER=false
if command -v docker &>/dev/null; then
    if docker info &>/dev/null; then
        HAS_DOCKER=true
        echo -e "${GREEN}✔ Docker detectado e em execução.${NC}"
    else
        echo -e "${YELLOW}⚠ Docker instalado, mas o serviço não está rodando.${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Docker não encontrado. A configuração automática do PostgreSQL local será ignorada.${NC}"
fi

# 2. Configurando o Ambiente Virtual (venv)
if [ ! -d ".venv" ]; then
    echo -e "\n${YELLOW}Criando ambiente virtual Python (.venv)...${NC}"
    $PYTHON_EXE -m venv .venv
    if [ $? -ne 0 ]; then
        echo -e "${RED}Erro ao criar o ambiente virtual.${NC}"
        exit 1
    fi
fi

# Determinar caminho de ativação
if [ "$IS_WINDOWS" = true ]; then
    VENV_ACTIVATE=".venv/Scripts/activate"
else
    VENV_ACTIVATE=".venv/bin/activate"
fi

if [ -f "$VENV_ACTIVATE" ]; then
    echo -e "${GREEN}Ativando ambiente virtual...${NC}"
    source "$VENV_ACTIVATE"
else
    echo -e "${RED}Erro: Não foi possível localizar o script de ativação em $VENV_ACTIVATE.${NC}"
    exit 1
fi

# Atualizar pip e instalar dependências
echo -e "${YELLOW}Instalando dependências do projeto (modo editável com dev)...${NC}"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
if [ $? -ne 0 ]; then
    echo -e "${RED}Erro ao instalar dependências do projeto.${NC}"
    exit 1
fi
echo -e "${GREEN}✔ Dependências instaladas com sucesso.${NC}"

# 3. Configuração do arquivo .env
if [ ! -f ".env" ]; then
    echo -e "\n${YELLOW}Criando arquivo .env a partir do exemplo...${NC}"
    cp .env.example .env
fi

# Funções auxiliares para leitura e escrita no .env utilizando Python
update_env() {
    local key=$1
    local value=$2
    python -c "
import os
path = '.env'
lines = []
found = False
if os.path.exists(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
for i, line in enumerate(lines):
    if line.strip().startswith('$key='):
        lines[i] = f'$key={value}\n'
        found = True
        break
if not found:
    lines.append(f'$key={value}\n')
with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
"
}

get_env_val() {
    local key=$1
    python -c "
import os
path = '.env'
if not os.path.exists(path):
    print('')
    exit(0)
with open(path, 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip().startswith('$key='):
            val = line.split('=', 1)[1].strip()
            print(val)
            exit(0)
print('')
"
}

generate_secret() {
    python -c "import secrets; print(secrets.token_hex(32))"
}

# Configuração interativa
echo -e "\n${GREEN}--- Configuração do Agente ---${NC}"
current_app_name=$(get_env_val "APP_NAME")
read -p "Nome do agente / aplicação [$current_app_name]: " input_app_name
if [ ! -z "$input_app_name" ]; then
    update_env "APP_NAME" "$input_app_name"
fi

# Chaves de API
echo -e "\n${GREEN}--- Chaves de API de IA ---${NC}"
current_openai=$(get_env_val "OPENAI_API_KEY")
if [[ -z "$current_openai" || "$current_openai" == "your-openai-key-here" ]]; then
    read -p "Deseja inserir sua OPENAI_API_KEY agora? (s/n): " set_openai
    if [[ "$set_openai" =~ ^[Ss]$ ]]; then
        read -sp "Insira a OPENAI_API_KEY: " openai_key
        echo ""
        update_env "OPENAI_API_KEY" "$openai_key"
    fi
else
    echo -e "OPENAI_API_KEY já configurada no .env."
fi

current_anthropic=$(get_env_val "ANTHROPIC_API_KEY")
if [[ -z "$current_anthropic" || "$current_anthropic" == "your-anthropic-key-here" ]]; then
    read -p "Deseja inserir sua ANTHROPIC_API_KEY agora? (s/n): " set_anthropic
    if [[ "$set_anthropic" =~ ^[Ss]$ ]]; then
        read -sp "Insira a ANTHROPIC_API_KEY: " anthropic_key
        echo ""
        update_env "ANTHROPIC_API_KEY" "$anthropic_key"
    fi
fi

# Gerar chaves secretas e segredos de hash automaticamente se estiverem vazios/placeholder
echo -e "\n${GREEN}--- Gerando segredos criptográficos obrigatórios ---${NC}"
for secret_var in API_SECRET_KEY PERSISTENCE_HASH_SECRET IDENTITY_HASH_SECRET OTP_DIGEST_SECRET OUTBOX_WEBHOOK_SECRET; do
    curr_val=$(get_env_val "$secret_var")
    if [[ -z "$curr_val" || "$curr_val" == "<"* || "$curr_val" == "your-"* ]]; then
        new_secret=$(generate_secret)
        update_env "$secret_var" "$new_secret"
        echo -e "✔ Gerado segredo seguro para $secret_var"
    fi
done

# 4. Configuração do Banco de Dados PostgreSQL/pgvector
echo -e "\n${GREEN}--- Configuração do Banco de Dados ---${NC}"
if [ "$HAS_DOCKER" = true ]; then
    read -p "Deseja configurar e subir um container PostgreSQL + pgvector local via Docker? (s/n): " run_db
    if [[ "$run_db" =~ ^[Ss]$ ]]; then
        # Verificar se já existe container com mesmo nome
        if docker ps -a --format '{{.Names}}' | grep -q "^supportfaq_db$"; then
            echo -e "${YELLOW}Um container chamado 'supportfaq_db' já existe.${NC}"
            read -p "Deseja recriá-lo? (Isso apagará dados anteriores do container!) (s/n): " recreate_db
            if [[ "$recreate_db" =~ ^[Ss]$ ]]; then
                docker rm -f supportfaq_db &>/dev/null
            fi
        fi

        # Se não existe ou foi removido, cria um novo
        if ! docker ps -a --format '{{.Names}}' | grep -q "^supportfaq_db$"; then
            read -p "Usuário do banco de dados [supportfaq]: " db_user
            db_user=${db_user:-supportfaq}
            
            read -sp "Senha do banco de dados [gerada automaticamente se vazio]: " db_pass
            echo ""
            if [ -z "$db_pass" ]; then
                db_pass=$(generate_secret | cut -c1-16)
                echo -e "Senha gerada: ${YELLOW}$db_pass${NC} (guarde esta senha!)"
            fi

            echo -e "${YELLOW}Iniciando container PostgreSQL com pgvector...${NC}"
            docker run -d \
              --name supportfaq_db \
              -e POSTGRES_DB=supportfaq \
              -e POSTGRES_USER="$db_user" \
              -e POSTGRES_PASSWORD="$db_pass" \
              -p 127.0.0.1:5432:5432 \
              pgvector/pgvector:pg16

            if [ $? -eq 0 ]; then
                echo -e "${GREEN}✔ Container 'supportfaq_db' iniciado com sucesso.${NC}"
                # Atualiza variáveis no .env
                update_env "DATABASE_URL" "postgresql://$db_user:$db_pass@127.0.0.1:5432/supportfaq"
                update_env "RETRIEVAL_BACKEND" "pgvector"
                update_env "PERSISTENCE_BACKEND" "postgres"
                update_env "SESSION_DOMAIN_STORE_BACKEND" "postgres"
                # Espera o postgres ficar pronto para aceitar conexões
                echo -e "${YELLOW}Aguardando o banco iniciar completamente (5 segundos)...${NC}"
                sleep 5
            else
                echo -e "${RED}Erro ao iniciar o container Docker.${NC}"
            fi
        else
            echo -e "Reutilizando container 'supportfaq_db' existente."
        fi
    fi
fi

# 5. Aplicar as migrations
echo -e "\n${GREEN}--- Executando Migrações do Banco ---${NC}"
db_url=$(get_env_val "DATABASE_URL")
if [ -z "$db_url" ]; then
    echo -e "${YELLOW}Nenhuma DATABASE_URL configurada no .env. Migrações ignoradas.${NC}"
else
    python -m scripts.migrate status
    python -m scripts.migrate apply
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✔ Migrações aplicadas com sucesso.${NC}"
    else
        echo -e "${RED}Erro ao aplicar migrações.${NC}"
    fi
fi

# 6. Ingestão de Conhecimento
echo -e "\n${GREEN}--- Ingestão da Base de Conhecimento ---${NC}"
openai_key_check=$(get_env_val "OPENAI_API_KEY")
if [[ -z "$openai_key_check" || "$openai_key_check" == "your-openai-key-here" ]]; then
    echo -e "${YELLOW}Aviso: OPENAI_API_KEY ausente ou inválida. A ingestão vetorial pode falhar sem chaves de embeddings.${NC}"
fi

read -p "Deseja rodar a ingestão dos domínios padrão agora? (s/n): " run_ingest
if [[ "$run_ingest" =~ ^[Ss]$ ]]; then
    python scripts/ingest_domain_pgvector.py
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✔ Ingestão concluída com sucesso.${NC}"
    else
        echo -e "${RED}Erro ao realizar ingestão. Verifique sua chave OpenAI ou status do banco.${NC}"
    fi
fi

# 7. Validação e Execução
echo -e "\n${GREEN}--- Validação do Ambiente ---${NC}"
read -p "Deseja rodar os testes da aplicação para validar? (s/n): " run_tests
if [[ "$run_tests" =~ ^[Ss]$ ]]; then
    python -m pytest
fi

echo -e "\n${GREEN}=============================================${NC}"
echo -e "${GREEN}    Configuração concluída com sucesso!       ${NC}"
echo -e "${GREEN}=============================================${NC}"

read -p "Deseja iniciar o servidor FastAPI local agora? (s/n): " run_server
if [[ "$run_server" =~ ^[Ss]$ ]]; then
    echo -e "${YELLOW}Iniciando API em http://127.0.0.1:8000 ...${NC}"
    uvicorn app.main:app --host 127.0.0.1 --port 8000
fi
