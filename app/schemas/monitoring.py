from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

class HealthCheckCreate(BaseModel):
    project_id: int
    enabled: bool = True
    protocol: str = "http"
    host: str = "localhost"
    port: Optional[int] = None
    path: str = "/"
    interval_seconds: int = 60

class HealthCheckUpdate(BaseModel):
    enabled: Optional[bool] = None
    protocol: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    path: Optional[str] = None
    interval_seconds: Optional[int] = None

class HealthCheckOut(BaseModel):
    id: int
    project_id: int
    enabled: bool
    protocol: str
    host: str
    port: Optional[int]
    path: str
    interval_seconds: int
    last_check: Optional[datetime] = None
    last_status: str
    last_latency_ms: Optional[int]
    class Config:
        from_attributes = True

class MetricOut(BaseModel):
    id: int
    project_id: Optional[int]
    container_id: Optional[str]
    container_name: Optional[str]
    metric_type: str
    value: str
    recorded_at: datetime
    class Config:
        from_attributes = True

class AuditLogOut(BaseModel):
    id: int
    user: Optional[str]
    action: str
    target: Optional[str]
    ip: Optional[str]
    user_agent: Optional[str]
    timestamp: datetime
    details: str
    class Config:
        from_attributes = True

class WebhookCreate(BaseModel):
    name: str
    url: str
    events: str = "deploy,health_fail"
    enabled: bool = True

class WebhookOut(BaseModel):
    id: int
    name: str
    url: str
    events: str
    enabled: bool
    created_at: datetime
    class Config:
        from_attributes = True

class NotificationOut(BaseModel):
    id: int
    level: str
    title: str
    body: str
    read: bool
    created_at: datetime
    class Config:
        from_attributes = True
