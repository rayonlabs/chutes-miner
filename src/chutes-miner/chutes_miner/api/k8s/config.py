from dataclasses import dataclass, field
import yaml
from kubernetes import client, config
from typing import Dict, List, Optional

@dataclass
class KubeCluster:
    """Represents a Kubernetes cluster configuration"""
    name: str
    server: str
    certificate_authority_data: Optional[str] = None
    insecure_skip_tls_verify: Optional[bool] = None
    
    @classmethod
    def from_dict(cls, name: str, cluster_dict: dict) -> 'KubeCluster':
        return cls(
            name=name,
            server=cluster_dict['server'],
            certificate_authority_data=cluster_dict.get('certificate-authority-data'),
            insecure_skip_tls_verify=cluster_dict.get('insecure-skip-tls-verify')
        )
    
    def to_dict(self) -> dict:
        cluster_dict = {'server': self.server}
        if self.certificate_authority_data:
            cluster_dict['certificate-authority-data'] = self.certificate_authority_data
        if self.insecure_skip_tls_verify is not None:
            cluster_dict['insecure-skip-tls-verify'] = self.insecure_skip_tls_verify
        return cluster_dict

@dataclass
class KubeUser:
    """Represents a Kubernetes user configuration"""
    name: str
    token: Optional[str] = None
    client_certificate_data: Optional[str] = None
    client_key_data: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    
    @classmethod
    def from_dict(cls, name: str, user_dict: dict) -> 'KubeUser':
        return cls(
            name=name,
            token=user_dict.get('token'),
            client_certificate_data=user_dict.get('client-certificate-data'),
            client_key_data=user_dict.get('client-key-data'),
            username=user_dict.get('username'),
            password=user_dict.get('password')
        )
    
    def to_dict(self) -> dict:
        user_dict = {}
        if self.token:
            user_dict['token'] = self.token
        if self.client_certificate_data:
            user_dict['client-certificate-data'] = self.client_certificate_data
        if self.client_key_data:
            user_dict['client-key-data'] = self.client_key_data
        if self.username:
            user_dict['username'] = self.username
        if self.password:
            user_dict['password'] = self.password
        return user_dict

@dataclass
class KubeContext:
    """Represents a Kubernetes context configuration"""
    name: str
    cluster: KubeCluster
    user: KubeUser
    namespace: str = 'default'
    
    @classmethod
    def from_dict(cls, name: str, context_dict: dict, clusters: Dict[str, KubeCluster], users: Dict[str, KubeUser]) -> 'KubeContext':
        cluster_name = context_dict['cluster']
        user_name = context_dict['user']
        
        if cluster_name not in clusters:
            raise ValueError(f"Cluster {cluster_name} not found")
        if user_name not in users:
            raise ValueError(f"User {user_name} not found")
        
        return cls(
            name=name,
            cluster=clusters[cluster_name],
            user=users[user_name],
            namespace=context_dict.get('namespace', 'default')
        )
    
    def to_dict(self) -> dict:
        return {
            'cluster': self.cluster.name,
            'user': self.user.name,
            'namespace': self.namespace
        }

@dataclass
class KubeConfig:
    """Top-level Kubernetes configuration object"""
    
    apiVersion: str = "v1"
    kind: str = "Config"
    current_context: Optional[str] = None
    preferences: dict = field(default_factory=dict)
    clusters: list[KubeCluster] = field(default_factory=list)
    contexts: list[KubeContext] = field(default_factory=list)
    users: list[KubeUser] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, config_dict: dict) -> 'KubeConfig':
        """Create KubeConfig from dictionary"""
        # Parse clusters
        clusters = []
        for cluster_dict in config_dict.get('clusters', []):
            cluster = KubeCluster.from_dict(cluster_dict['name'], cluster_dict['cluster'])
            clusters.append(cluster)
        
        # Parse users
        users = []
        for user_dict in config_dict.get('users', []):
            user = KubeUser.from_dict(user_dict['name'], user_dict['user'])
            users.append(user)
        
        # Create lookup dictionaries for context creation
        cluster_lookup = {c.name: c for c in clusters}
        user_lookup = {u.name: u for u in users}
        
        # Parse contexts
        contexts = []
        for context_dict in config_dict.get('contexts', []):
            context = KubeContext.from_dict(
                context_dict['name'], 
                context_dict['context'], 
                cluster_lookup, 
                user_lookup
            )
            contexts.append(context)
        
        return cls(
            apiVersion=config_dict.get('apiVersion', 'v1'),
            kind=config_dict.get('kind', 'Config'),
            current_context=config_dict.get('current-context'),
            preferences=config_dict.get('preferences', {}),
            clusters=clusters,
            contexts=contexts,
            users=users
        )
    
    def to_dict(self) -> dict:
        """Convert KubeConfig to dictionary format"""
        config_dict = {
            "apiVersion": self.apiVersion,
            "kind": self.kind,
            "clusters": [
                {"name": cluster.name, "cluster": cluster.to_dict()}
                for cluster in self.clusters
            ],
            "users": [
                {"name": user.name, "user": user.to_dict()}
                for user in self.users
            ],
            "contexts": [
                {"name": context.name, "context": context.to_dict()}
                for context in self.contexts
            ]
        }
        
        if self.current_context:
            config_dict["current-context"] = self.current_context
        
        if self.preferences:
            config_dict["preferences"] = self.preferences
        
        return config_dict

    def get_cluster(self, name: str) -> Optional[KubeCluster]:
        """Get cluster by name"""
        return next((c for c in self.clusters if c.name == name), None)
    
    def get_user(self, name: str) -> Optional[KubeUser]:
        """Get user by name"""
        return next((u for u in self.users if u.name == name), None)
    
    def get_context(self, name: str) -> Optional[KubeContext]:
        """Get context by name"""
        return next((c for c in self.contexts if c.name == name), None)
    
    def _add_cluster(self, cluster: KubeCluster):
        """Add or update a cluster"""
        # Remove existing cluster with same name
        self.clusters = [c for c in self.clusters if c.name != cluster.name]
        self.clusters.append(cluster)
    
    def _add_user(self, user: KubeUser):
        """Add or update a user"""
        # Remove existing user with same name
        self.users = [u for u in self.users if u.name != user.name]
        self.users.append(user)
    
    def _add_context(self, context: KubeContext):
        """Add or update a context"""
        # Remove existing context with same name
        self.contexts = [c for c in self.contexts if c.name != context.name]
        self.contexts.append(context)
        # Ensure cluster and user exist, overwrite if conflicts
        self._add_cluster(context.cluster)
        self._add_user(context.user)
        
        # Set as current context if none set
        if not self.current_context:
            self.current_context = context.name
    
    def remove_context(self, context_name: str) -> bool:
        """Remove a context and orphaned clusters/users"""
        context = self.get_context(context_name)
        if not context:
            return False
        
        # Remove context
        self.contexts = [c for c in self.contexts if c.name != context_name]
        
        # Update current context if it was the removed one
        if self.current_context == context_name:
            self.current_context = self.contexts[0].name if self.contexts else None
        
        # Check if cluster/user are still referenced
        cluster_referenced = any(ctx.cluster.name == context.cluster.name for ctx in self.contexts)
        user_referenced = any(ctx.user.name == context.user.name for ctx in self.contexts)
        
        if not cluster_referenced:
            self.clusters = [c for c in self.clusters if c.name != context.cluster.name]
        if not user_referenced:
            self.users = [u for u in self.users if u.name != context.user.name]
        
        return True
    
    def merge(self, other: 'KubeConfig'):
        """Merge another KubeConfig into this one"""
        # Direct merge without prefixing
        for cluster in other.clusters:
            self._add_cluster(cluster)
        for user in other.users:
            self._add_user(user)
        for context in other.contexts:
            self._add_context(context)

class MultiClusterKubeConfig:

    _instance: Optional["MultiClusterKubeConfig"] = None

    def __init__(self):
        self._kubeconfig: KubeConfig = KubeConfig()

    def __new__(cls, *args, **kwargs):
        """
        Factory method that creates either a SingleClusterK8sOperator or KarmadaK8sOperator
        based on the detected infrastructure.
        """
        # If we don't have an instance, set it (singleton)
        if cls._instance is None:
            cls._instance = super().__new__(MultiClusterKubeConfig)

        return cls._instance

    @property
    def kubeconfig(self) -> KubeConfig:
        return self._kubeconfig
    
    @property
    def context_names(self) -> List[str]:
        """Get list of available context names"""
        return [ctx.name for ctx in self._kubeconfig.contexts]

    @property
    def contexts(self) -> List[KubeContext]:
        """Get list of available contexts"""
        return self._kubeconfig.contexts

    @property
    def clusters(self) -> List[KubeCluster]:
        """Get list of available contexts"""
        return self._kubeconfig.clusters

    @property
    def users(self) -> List[KubeUser]:
        """Get list of available contexts"""
        return self._kubeconfig.users

    def get_context(self, context_name: str) -> KubeContext:
        if context_name not in self.context_names:
            raise ValueError(f"Context {context_name} not found")
                    
        return next([ctx for ctx in self.contexts if ctx.name == context_name])

    def add_config(self, kubeconfig: str):
        """Add a cluster configuration from database to the consolidated config"""
        """Add a cluster configuration from database"""
        other_config = KubeConfig.from_dict(yaml.safe_load(kubeconfig))
        
        # Merge with prefix to avoid naming conflicts
        self.kubeconfig.merge(other_config)
    
    def set_context(self, context_name: str):
        """Set the current context"""
        if context_name not in self.context_names:
            raise ValueError(f"Context {context_name} not found")
        self._kubeconfig.current_context = context_name