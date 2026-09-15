
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

ASSET_TYPES = {"currency", "equity", "bond", "fund", "real_estate",
               "commodity", "invoice", "carbon", "other"}
KYC_STATUS = {"pending", "approved", "rejected", "expired", "revoked"}
KYC_LEVELS = {"basic", "accredited", "institutional"}


@dataclass
class AssetDefinition:
    asset_id: str
    name: str
    symbol: str
    asset_type: str
    decimals: int
    issuer: str
    transfer_agent: str
    custodian: str = ""
    isin: str = ""
    total_supply: float = 0.0
    max_supply: float = 0.0
    transfer_restricted: bool = True
    legal_doc_hash: str = ""
    created_at: float = field(default_factory=time.time)
    frozen: bool = False
    metadata: dict = field(default_factory=dict)

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ComplianceRecord:
    address: str
    status: str = "pending"
    level: str = "basic"
    jurisdiction: str = ""
    verified_by: str = ""
    verified_at: float = 0.0
    expires_at: float = 0.0
    restrictions: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def is_valid(self, now=None):
        if self.status != "approved": return False
        if self.expires_at and (now or time.time()) > self.expires_at:
            return False
        return True

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TransferRule:
    require_kyc_sender: bool = True
    require_kyc_receiver: bool = True
    min_kyc_level: str = "basic"
    allowed_jurisdictions: List[str] = field(default_factory=list)
    blocked_jurisdictions: List[str] = field(default_factory=list)
    max_holding_per_address: float = 0.0
    lockup_until: float = 0.0
    min_transfer_amount: float = 0.0

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class AssetRegistry:
    def __init__(self):
        self.assets: Dict[str, AssetDefinition] = {}
        self.compliance: Dict[str, ComplianceRecord] = {}
        self.rules: Dict[str, TransferRule] = {}
        self.regulator: str = ""

    def add_asset(self, asset):
        if asset.asset_id in self.assets: return False
        if asset.asset_type not in ASSET_TYPES: return False
        if not asset.issuer or not asset.issuer.startswith("brn1"): return False
        self.assets[asset.asset_id] = asset
        if asset.asset_id not in self.rules:
            self.rules[asset.asset_id] = TransferRule()
        return True

    def update_asset(self, asset_id, updates):
        a = self.assets.get(asset_id)
        if not a: return False
        for k, v in updates.items():
            if hasattr(a, k) and k not in ("asset_id", "created_at"):
                setattr(a, k, v)
        return True

    def get_asset(self, asset_id): return self.assets.get(asset_id)

    def set_compliance(self, rec):
        if rec.status not in KYC_STATUS or rec.level not in KYC_LEVELS:
            return False
        self.compliance[rec.address] = rec
        return True

    def get_compliance(self, addr): return self.compliance.get(addr)

    def is_kyc_valid(self, addr, min_level="basic"):
        rec = self.compliance.get(addr)
        if not rec or not rec.is_valid(): return False
        order = {"basic": 0, "accredited": 1, "institutional": 2}
        return order.get(rec.level, -1) >= order.get(min_level, 0)

    def set_rule(self, asset_id, rule):
        if asset_id not in self.assets: return False
        self.rules[asset_id] = rule
        return True

    def get_rule(self, asset_id):
        return self.rules.get(asset_id, TransferRule())

    def can_issue(self, asset_id, addr):
        a = self.assets.get(asset_id)
        return bool(a and a.issuer == addr)

    def can_manage_kyc(self, asset_id, addr):
        a = self.assets.get(asset_id)
        if not a: return False
        return addr in (a.issuer, a.transfer_agent) or addr == self.regulator

    def can_freeze(self, asset_id, addr):
        a = self.assets.get(asset_id)
        if not a: return False
        return addr in (a.issuer, a.transfer_agent, self.regulator)

    def validate_transfer(self, asset_id, sender, receiver, amount,
                          receiver_balance_after):
        a = self.assets.get(asset_id)
        if not a: return False, f"ativo '{asset_id}' nao existe"
        if a.frozen: return False, "ativo congelado"
        if amount <= 0: return False, "valor deve ser positivo"
        rule = self.get_rule(asset_id)
        if rule.lockup_until and time.time() < rule.lockup_until:
            return False, "lockup ativo"
        if amount < rule.min_transfer_amount:
            return False, "abaixo do minimo"
        if a.transfer_restricted:
            if rule.require_kyc_sender and not self.is_kyc_valid(sender, rule.min_kyc_level):
                return False, "remetente sem KYC"
            if rule.require_kyc_receiver and not self.is_kyc_valid(receiver, rule.min_kyc_level):
                return False, "destinatario sem KYC"
            rec = self.compliance.get(receiver)
            if rec:
                if rule.allowed_jurisdictions and rec.jurisdiction not in rule.allowed_jurisdictions:
                    return False, "jurisdicao nao permitida"
                if rec.jurisdiction in rule.blocked_jurisdictions:
                    return False, "jurisdicao bloqueada"
                if "block_transfer" in rec.restrictions:
                    return False, "restricao de transferencia"
        if rule.max_holding_per_address > 0 and receiver_balance_after > rule.max_holding_per_address:
            return False, "excederia maximo"
        return True, "ok"

    def to_dict(self):
        return {
            "assets": {k: v.to_dict() for k, v in self.assets.items()},
            "compliance": {k: v.to_dict() for k, v in self.compliance.items()},
            "rules": {k: v.to_dict() for k, v in self.rules.items()},
            "regulator": self.regulator,
        }

    @classmethod
    def from_dict(cls, d):
        r = cls()
        r.regulator = d.get("regulator", "")
        for k, v in d.get("assets", {}).items():
            r.assets[k] = AssetDefinition.from_dict(v)
        for k, v in d.get("compliance", {}).items():
            r.compliance[k] = ComplianceRecord.from_dict(v)
        for k, v in d.get("rules", {}).items():
            r.rules[k] = TransferRule.from_dict(v)
        return r
