from typing import List, Dict, Any, Optional
import json

class ResourceSelector:
    def __init__(self, api_version: str, kind: str, name: Optional[str] = None, namespace: Optional[str] = None, label_selector: Optional[Dict[str, str]] = None):
        self.api_version = api_version
        self.kind = kind
        self.name = name
        self.namespace = namespace
        self.label_selector = label_selector

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "apiVersion": self.api_version,
            "kind": self.kind
        }
        if self.name:
            result["name"] = self.name
        if self.namespace:
            result["namespace"] = self.namespace
        if self.label_selector:
            result["labelSelector"] = {"matchLabels": self.label_selector}
        return result

class ClusterAffinity:
    def __init__(self, cluster_names: Optional[List[str]] = None, field_selector: Optional[Dict[str, str]] = None, label_selector: Optional[Dict[str, str]] = None):
        self.cluster_names = cluster_names or []
        self.field_selector = field_selector
        self.label_selector = label_selector

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        if self.cluster_names:
            result["clusterNames"] = self.cluster_names
        if self.field_selector:
            result["fieldSelector"] = self.field_selector
        if self.label_selector:
            result["labelSelector"] = {"matchLabels": self.label_selector}
        return result

class ReplicaScheduling:
    def __init__(self, scheduling_type: str = "Divided", weighted_clusters: Optional[List[Dict[str, Any]]] = None):
        self.scheduling_type = scheduling_type
        self.weighted_clusters = weighted_clusters

    def to_dict(self) -> Dict[str, Any]:
        result = {"replicaSchedulingType": self.scheduling_type}
        if self.weighted_clusters:
            result["weightedClusters"] = self.weighted_clusters
        return result

class SpreadConstraint:
    def __init__(self, spread_by_field: str, min_groups: int = 1, max_groups: Optional[int] = None):
        self.spread_by_field = spread_by_field
        self.min_groups = min_groups
        self.max_groups = max_groups

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "spreadByField": self.spread_by_field,
            "minGroups": self.min_groups
        }
        if self.max_groups:
            result["maxGroups"] = self.max_groups
        return result

class Placement:
    def __init__(self, cluster_affinity: Optional[ClusterAffinity] = None, 
                 replica_scheduling: Optional[ReplicaScheduling] = None,
                 spread_constraints: Optional[List[SpreadConstraint]] = None):
        self.cluster_affinity = cluster_affinity or ClusterAffinity()
        self.replica_scheduling = replica_scheduling
        self.spread_constraints = spread_constraints or []

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        if self.cluster_affinity.to_dict():
            result["clusterAffinity"] = self.cluster_affinity.to_dict()
        if self.replica_scheduling:
            result["replicaScheduling"] = self.replica_scheduling.to_dict()
        if self.spread_constraints:
            result["spreadConstraints"] = [sc.to_dict() for sc in self.spread_constraints]
        return result

class PropagationDependency:
    def __init__(self, resource_selectors: List[ResourceSelector]):
        self.resource_selectors = resource_selectors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resourceSelectors": [rs.to_dict() for rs in self.resource_selectors]
        }

class Failover:
    def __init__(self, grace_period_seconds: int = 300, purge_mode: str = "Cascading"):
        self.grace_period_seconds = grace_period_seconds
        self.purge_mode = purge_mode

    def to_dict(self) -> Dict[str, Any]:
        return {
            "application": {
                "gracePeriodSeconds": self.grace_period_seconds,
                "purgeMode": self.purge_mode
            }
        }

class PropagationPolicy:
    def __init__(self, name: str, namespace: str = "default", 
                 resource_selectors: Optional[List[ResourceSelector]] = None,
                 placement: Optional[Placement] = None,
                 priority: int = 1,
                 scheduler_name: str = "default-scheduler",
                 propagation_dependencies: Optional[List[PropagationDependency]] = None,
                 failover: Optional[Failover] = None):
        self.name = name
        self.namespace = namespace
        self.resource_selectors = resource_selectors or []
        self.placement = placement or Placement()
        self.priority = priority
        self.scheduler_name = scheduler_name
        self.propagation_dependencies = propagation_dependencies or []
        self.failover = failover

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "apiVersion": "policy.karmada.io/v1alpha1",
            "kind": "PropagationPolicy",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace
            },
            "spec": {
                "resourceSelectors": [rs.to_dict() for rs in self.resource_selectors],
                "placement": self.placement.to_dict(),
                "priority": self.priority,
                "schedulerName": self.scheduler_name
            }
        }
        
        if self.propagation_dependencies:
            result["spec"]["propagationDependencies"] = [pd.to_dict() for pd in self.propagation_dependencies]
        
        if self.failover:
            result["spec"]["failover"] = self.failover.to_dict()
            
        return result
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    def __str__(self) -> str:
        return self.to_json()