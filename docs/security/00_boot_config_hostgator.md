# Configurações de Boot — VPS HostGator
**Memória de Referência do Servidor**
VPS HostGator | 129.121.50.85 | AlmaLinux 9.7
Levantado em: 12/05/2026 — Acesso inicial confirmado

---

## 1. Identidade do Servidor

| Campo | Valor |
|---|---|
| Hostname | vps-15336368.hubhostgator.com |
| Provedor | Hostgator — OpenStack Compute / KVM |
| Sistema Operacional | AlmaLinux 9.7 (Moss Jungle Cat) |
| Kernel | Linux 5.14.0-611.54.3.el9_7.x86_64 (x86-64) |
| CPU | AMD EPYC — KVM / RDO — OpenStack Compute |
| Firmware | 1.16.3-4.el9.alma.1 |
| Machine ID | 5d3790b1ee6630f9900c8d370db15365 |
| Boot ID (atual) | 14001ff54dd4445abada24f1c7cec8ec |
| Virtualização | KVM |
| Data do Levantamento | 12/05/2026 — Acesso inicial |

---

## 2. Recursos de Hardware

| Recurso | Total | Em Uso | Disponível |
|---|---|---|---|
| RAM | 7,5 GB | 474 MB (~6%) | ~7,0 GB |
| Swap | 0 B | 0 B | Não configurado |
| Disco — /dev/sda3 (/) | 196 GB (SSD) | 3,8 GB (2%) | 184 GB (98%) |
| Disco — /dev/sda2 (/boot) | 974 MB | 408 MB (46%) | 499 MB (54%) |
| CPU | vCPU (KVM) | ~2–5% (idle) | ~95%+ |

> ⚠️ **SWAP INATIVO:** Nenhum swap configurado. Recomendado criar swapfile de 2–4 GB para evitar OOM em picos de carga.

---

## 3. Configuração de Rede

| Parâmetro | Valor |
|---|---|
| Endereço IPv4 | 129.121.50.85 |
| SSH Port | 22022 (não padrão — OK) |
| Portas abertas confirmadas | Apenas 22022/tcp (IPv4 + IPv6) |
| Firewall | A verificar — firewalld não confirmado no boot |
| Falhas de login no último acesso | 2 tentativas falhas detectadas |

---

## 4. Serviços Ativos no Boot (systemd)

| Serviço | Status | Observação / Risco |
|---|---|---|
| auditd | ✅ ATIVO | Auditoria de sistema ativa — excelente |
| fail2ban | ✅ ATIVO | Proteção brute force ativa |
| docker + containerd | ✅ ATIVO | Engine principal de containers |
| sshd (porta 22022) | ✅ ATIVO | Porta não padrão — OK |
| chronyd (NTP) | ✅ ATIVO | Sincronização de tempo ativa |
| collectd | ✅ ATIVO | Coleta de métricas do sistema |
| crond | ✅ ATIVO | Agendador de tarefas ativo |
| rsyslog | ✅ ATIVO | Log centralizado ativo |
| NetworkManager | ✅ ATIVO | Gerenciamento de rede |
| qemu-guest-agent | ✅ ATIVO | Integração KVM/Hostgator |
| unattended-upgrades | ⚠️ NÃO VISÍVEL | Não confirmado — AlmaLinux usa dnf-automatic |
| UFW / iptables | ⚠️ NÃO CONFIRMADO | AlmaLinux usa firewalld — verificar |
| AppArmor / SELinux | ⚠️ NÃO CONFIRMADO | AlmaLinux usa SELinux por padrão — verificar |

---

## 5. Containers Docker

Docker e containerd estão ativos. Nenhum container em execução foi identificado no levantamento inicial — VPS em estado limpo (fresh install ou recém-provisionada).

```bash
# Confirmar estado dos containers
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
```

---

## 6. Alertas e Pontos de Atenção

| # | Alerta | Severidade | Ação Recomendada |
|---|---|---|---|
| 1 | 2 tentativas de login falhas | ⚠️ ALTA | `fail2ban-client status sshd` + `tail -50 /var/log/secure` |
| 2 | SWAP inativo (0B) | ⚠️ MÉDIA | `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile` |
| 3 | Firewall não confirmado | ⚠️ ALTA | `firewall-cmd --state && firewall-cmd --list-all` |
| 4 | SELinux status desconhecido | ⚠️ MÉDIA | `sestatus` — manter enforcing |
| 5 | dnf-automatic não confirmado | ⚠️ MÉDIA | `systemctl status dnf-automatic` |
| 6 | Nenhum container em execução | ℹ️ INFO | VPS em estado limpo — pronto para configuração |
| 7 | snapd ativo | ℹ️ INFO | `systemctl disable --now snapd` se não usado |

---

## 7. Diferenças Críticas: HostGator (AlmaLinux) vs Hostinger (Ubuntu)

| Item | Hostinger (Ubuntu 24.04) | HostGator (AlmaLinux 9.7) |
|---|---|---|
| Firewall | ufw | firewall-cmd (firewalld) |
| Gerenciador de pacotes | apt / apt-get | dnf / yum |
| MAC / Controle acesso | AppArmor | SELinux (enforcing por padrão) |
| Atualizações auto | unattended-upgrades | dnf-automatic |
| Log do sistema | journald + rsyslog | journald + rsyslog |
| auditd | A instalar | ✅ JÁ ATIVO |
| fail2ban | Ativo | ✅ JÁ ATIVO |
| Formato de pacotes | .deb | .rpm |

---

## 8. Próximos Passos — Checklist Inicial

| # | Ação | Comando | Prioridade |
|---|---|---|---|
| 1 | Verificar firewall | `firewall-cmd --state && firewall-cmd --list-all` | 🔴 CRÍTICA |
| 2 | Verificar SELinux | `sestatus` | 🟠 ALTA |
| 3 | Verificar tentativas SSH | `fail2ban-client status sshd && tail -50 /var/log/secure` | 🟠 ALTA |
| 4 | Verificar containers Docker | `docker ps -a` | 🟠 ALTA |
| 5 | Criar swapfile (2GB) | `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile` | 🟡 MÉDIA |
| 6 | Verificar atualizações pendentes | `dnf check-update` | 🟡 MÉDIA |
| 7 | Configurar dnf-automatic | `systemctl status dnf-automatic` | 🟡 MÉDIA |
| 8 | Restringir SSH por IP | `/etc/ssh/sshd_config` — AllowUsers + AllowHosts | 🟠 ALTA |
| 9 | Trocar senha root por chave SSH | `ssh-keygen + ssh-copy-id` | 🟠 ALTA |
| 10 | Documentar IPs autorizados | Registrar IPs de acesso permitidos | 🟠 ALTA |

---

*Gerado em 12/05/2026 | VPS HostGator | Confidencial*
