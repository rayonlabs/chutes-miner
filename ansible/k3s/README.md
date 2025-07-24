# Node bootstrapping

To ensure the highest probability of success, you should provision your servers with `Ubuntu 22.04`, preferably with NO nvidia driver installations if possible.

### Networking note before starting!!!

#### external_ip

The chutes API/validator sends traffic directly to each GPU node, and does not route through the main CPU node at all. For the system to work, this means each GPU node must have a publicly routeable IP address on each GPU node that is not behind a shared IP (since it uses kubernetes nodePort services).  This IP is the public IPv4, and must not be something in the private IP range like 192.168.0.0/16, 10.0.0.0/8, etc.

This public IP *must* be dedicated, and be the same for both egress and ingress. This means, for a node to pass validation, when the validator connects to it, the IP address you advertise as a miner must match the IP address the validator sees when your node fetches a remote token, i.e. you can't use a shared IP with NAT/port-mapping if the underlying nodes route back out to the internet with some other IPs.

## 1. Install ansible (on your local system, not the miner node(s))

### Mac

If you haven't yet, setup homebrew:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install ansible:
```bash
brew install ansible
```

### Ubuntu/Ubuntu (WSL)/aptitude based systems

```bash
sudo apt -y update && sudo apt -y install ansible python3-pip
```

### CentOS/RHEL/Fedora

Install epel repo if you haven't (and it's not fedora)
```bash
sudo dnf install epel-release -y
```

Install ansible:
```bash
sudo dnf install ansible -y
```

## 2. Install ansible collections

```bash
ansible-galaxy collection install community.general
ansible-galaxy collection install kubernetes.core
ansible-galaxy collection install ansible.posix
```

## OPTIONAL: Performance Tweaks for Ansible 

```bash
wget https://files.pythonhosted.org/packages/source/m/mitogen/mitogen-0.3.22.tar.gz
tar -xzf mitogen-0.3.22.tar.gz
```

Then in your ansible.cfg

```
[defaults]
strategy_plugins = /path/to/mitogen-0.3.22/ansible_mitogen/plugins/strategy
strategy = mitogen_linear
... leave the rest, and add this block below
[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=2m
```

## 3. Update inventory configuration

Using your favorite text editor (vim of course), edit inventory.yml to suite your needs.

For example:
```yaml

all:
  vars:
    ansible_user: ubuntu
    ansible_ssh_private_key_file: ~/.ssh/key.pem
    ssh_keys:
      - "ssh-rsa AAAAB... user@domain.com"
    # The username you want to use to login to those machines (and your public key will be added to).
    user: billybob

    # Local kubectl setup
    setup_local_kubeconfig: false # Set to true to setup kubeconfig on the ansible controller
    controller_kubeconfig: ~/.kube/chutes.config # Path to the ansible controller kubeconfig file you want to use
    controller_kubectl_staging_dir: "{{ '~/.kube' | expanduser }}/chutes-staging" # noqa var-naming[no-role-prefix]

  hosts:
    # This would be the main node, which runs postgres, redis, gepetto, etc.
    control:
      hosts:
        chutes-miner-cpu-0:
          ansible_host: 1.0.0.0
    workers:
      hosts:
        chutes-miner-gpu-0:
          ansible_host: 1.0.0.1
        chutes-miner-gpu-1:
          ansible_host: 1.0.0.2
```

## 4. Bootstrap the nodes

### Setup config and inventory

If you want to keep your inventory and ansible config separated from the repo be sure to update the following:
1. In your ansible config update the roles path to the absolute path to the karmada roles directory
```
[defaults]
roles_path = /path/to/chutes-miner/ansible/karmada/roles
```
2. Provide the path to your ansible inventory using `-i /path/to/inventory.yml` from the CLI

### Bootstrap

Execute the playbook from the `ansible/karmada` directory.

```bash
ansible-playbook playbooks/site.yml
```

## To add a new node, after the fact

First, update your inventory.yml with the new host configuration.

Then, use the `site.yml` playbook to add the new node:
```bash
ansible-playbook playbooks/site.yml --tags add-nodes
```