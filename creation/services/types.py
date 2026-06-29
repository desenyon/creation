from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class OpsResult:
    success: bool
    detail: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"success": self.success, "detail": self.detail, "data": self.data}
