#!/usr/bin/env bash
# One-time hardening + Docker install for a FRESH Ubuntu 24.04 droplet. Run as root:
#   bash vps-bootstrap.sh --ssh-from 203.0.113.7/32 [--user deploy]
# --ssh-from is the ONLY network allowed to reach SSH (your own public IP / VPN, CIDR).
#
# What it does (idempotent; safe to re-run):
#   * creates the deploy user with root's authorized SSH keys and asks for its sudo password
#   * SSH: keys only, no root login, only the deploy user (validated before reload)
#   * ufw: deny incoming except 22/tcp from --ssh-from and 80,443/tcp from anywhere
#   * unattended security upgrades, 2 GB swap, UTC clock
#   * Docker Engine + Compose plugin from Docker's apt repo, json-file log rotation
# It does NOT open the database or app ports, create cloud resources, or deploy anything.
# Keep your current SSH session open until you have logged in as the deploy user in a
# second terminal. Docker-published ports bypass ufw, which is why only Caddy publishes
# ports and why the DigitalOcean Cloud Firewall (see docs) is the outer layer.
set -euo pipefail

ssh_from="" user="deploy"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh-from) ssh_from="${2:?}"; shift 2 ;;
    --user) user="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ "$ssh_from" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ ]] \
  || { echo "--ssh-from must be an IPv4 CIDR such as 203.0.113.7/32" >&2; exit 1; }
[[ "$ssh_from" != "0.0.0.0/0" ]] || { echo "--ssh-from 0.0.0.0/0 would leave SSH open to everyone" >&2; exit 1; }
[[ "$user" =~ ^[a-z][a-z0-9_-]{0,31}$ ]] || { echo "invalid user name" >&2; exit 1; }
grep -q 'VERSION_ID="24.04"' /etc/os-release || echo "warning: tested on Ubuntu 24.04 only" >&2

export DEBIAN_FRONTEND=noninteractive
echo "== packages"
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl git ufw unattended-upgrades age jq dnsutils
timedatectl set-timezone UTC

echo "== user $user"
if ! id "$user" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$user"
fi
usermod -aG sudo "$user"
install -d -m 700 -o "$user" -g "$user" "/home/$user/.ssh"
if [[ ! -s "/home/$user/.ssh/authorized_keys" ]]; then
  [[ -s /root/.ssh/authorized_keys ]] || { echo "root has no authorized_keys to copy; add a key first" >&2; exit 1; }
  install -m 600 -o "$user" -g "$user" /root/.ssh/authorized_keys "/home/$user/.ssh/authorized_keys"
fi
if passwd -S "$user" | awk '{exit ($2 == "P") ? 0 : 1}'; then
  echo "sudo password already set for $user"
elif [[ -t 0 ]]; then
  echo "Set a sudo password for $user (store it in your password manager):"
  passwd "$user"
else
  echo "no TTY: set a sudo password later with 'passwd $user' (sudo will not work until then)" >&2
fi

echo "== ssh"
cat > /etc/ssh/sshd_config.d/10-safepay.conf <<EOF
# Managed by scripts/vps-bootstrap.sh
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers $user
MaxAuthTries 3
X11Forwarding no
EOF
sshd -t
systemctl reload ssh

echo "== firewall"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$ssh_from" to any port 22 proto tcp comment 'ssh (admin only)'
ufw allow 80/tcp comment 'http -> https redirect, ACME'
ufw allow 443/tcp comment 'https (caddy)'
ufw --force enable

echo "== automatic security updates"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades >/dev/null

echo "== swap"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-safepay-swap.conf && sysctl -q -p /etc/sysctl.d/99-safepay-swap.conf
fi

echo "== docker"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" },
  "live-restore": true
}
EOF
systemctl enable docker >/dev/null
systemctl restart docker
# Membership of the docker group is root-equivalent: only the deploy user gets it.
usermod -aG docker "$user"

echo
echo "bootstrap done. In a NEW terminal, before closing this one:"
echo "  ssh $user@<droplet-ip>      # must work; root login is now disabled"
ufw status verbose | sed 's/^/  /'
