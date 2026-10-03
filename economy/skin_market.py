"""
武器皮肤与市场交易系统 - 核心模块（修复版）

修复内容：
- 皮肤生成：完整随机（皮肤ID/磨损值/图案模板/稀有度）+ 保底机制 + 全局唯一记录
- 磨损计算：五种磨损分类 + 具体磨损数值 + 磨损影响价格
- 市场上架：手续费 + 上架/下架冷却 + 价格上下限
- 交易系统：所有权验证 + 交易冷却 + 完整交易日志
- 库存管理：容量限制 + 按磨损分类 + 重复检测 + JSON 持久化
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import json
import os
import random
import time
import uuid


# (上限, 分类名, 价格系数) —— 磨损值越低品相越好、价格越高
WEAR_CATEGORIES: List[Tuple[float, str, float]] = [
    (0.07, "崭新出厂", 1.00),
    (0.15, "略有磨损", 0.85),
    (0.38, "久经沙场", 0.70),
    (0.45, "破损不堪", 0.50),
    (1.00, "战痕累累", 0.30),
]

RARITIES = ["common", "rare", "epic", "legendary"]
RARITY_WEIGHTS = {"common": 0.70, "rare": 0.20, "epic": 0.08, "legendary": 0.02}
RARITY_BASE_PRICE = {"common": 10.0, "rare": 50.0, "epic": 200.0, "legendary": 1000.0}

SKIN_TEMPLATES = [
    (1, "AK-47 | 红线"),
    (2, "AWP | 巨龙传说"),
    (3, "M4A4 | 咆哮"),
    (4, "USP-S | 击杀确认"),
    (5, "沙漠之鹰 | 炽烈之炎"),
]

DEFAULT_CONFIG = {
    "seed": None,               # 随机种子，便于测试复现
    "pity_threshold": 10,       # 保底：连续 N 次开箱必出 rare 及以上
    "listing_fee_rate": 0.05,   # 上架手续费率（按标价收取）
    "listing_cooldown": 1.0,    # 上架/下架冷却（秒）
    "min_price": 0.1,           # 市场最低标价
    "max_price": 100000.0,      # 市场最高标价
    "trade_cooldown": 1.0,      # 交易冷却（秒）
    "inventory_capacity": 100,  # 库存容量上限
    "initial_balance": 1000.0,  # 新玩家初始余额
    "storage_path": None,       # 库存持久化文件路径（None 表示不持久化）
}


@dataclass
class Config:
    """配置项"""
    pass


class SkinMarket:
    """武器皮肤与市场交易系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = dict(DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        self._rng = random.Random(self.config.get("seed"))
        self._state = {}
        self._history = []
        self._skin_registry: Dict[str, Dict] = {}      # skin_uid -> skin（全局唯一记录）
        self._inventories: Dict[str, List[str]] = {}   # player_id -> [skin_uid]
        self._balances: Dict[str, float] = {}
        self._listings: Dict[str, Dict] = {}           # listing_id -> 挂单
        self._last_listing_action: Dict[str, float] = {}
        self._last_trade: Dict[str, float] = {}
        self._trade_log: List[Dict] = []
        self._pity_counter: Dict[str, int] = {}
        self._listing_seq = 0
        self._load()

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    def update(self, dt: float):
        """每帧更新"""
        pass

    def reset(self):
        """重置状态"""
        self._state = {}
        self._history = []
        self._skin_registry = {}
        self._inventories = {}
        self._balances = {}
        self._listings = {}
        self._last_listing_action = {}
        self._last_trade = {}
        self._trade_log = []
        self._pity_counter = {}
        self._listing_seq = 0

    def _now(self) -> float:
        return time.time()

    def get_balance(self, player_id: str) -> float:
        return self._balances.get(player_id, float(self.config["initial_balance"]))

    def set_balance(self, player_id: str, amount: float):
        self._balances[player_id] = float(amount)
        self._save()

    # ------------------------------------------------------------------
    # 磨损计算
    # ------------------------------------------------------------------
    def wear_calculation(self, wear_value: float) -> Dict:
        """根据磨损数值(0~1)计算磨损分类与价格系数"""
        wear_value = max(0.0, min(1.0, float(wear_value)))
        for upper, category, multiplier in WEAR_CATEGORIES:
            if wear_value <= upper:
                return {
                    "wear_value": wear_value,
                    "category": category,
                    "price_multiplier": multiplier,
                }
        upper, category, multiplier = WEAR_CATEGORIES[-1]
        return {"wear_value": wear_value, "category": category, "price_multiplier": multiplier}

    def calculate_price(self, skin: Dict) -> float:
        """皮肤价格 = 稀有度基础价 × 磨损价格系数"""
        base = RARITY_BASE_PRICE.get(skin.get("rarity", "common"), RARITY_BASE_PRICE["common"])
        multiplier = self.wear_calculation(skin.get("wear_value", 0.0))["price_multiplier"]
        return round(base * multiplier, 2)

    # ------------------------------------------------------------------
    # 皮肤生成（完整随机 + 保底 + 唯一记录）
    # ------------------------------------------------------------------
    def generate_skin(self, player_id: Optional[str] = None) -> Dict:
        """生成一个皮肤：随机皮肤ID/磨损值/图案模板/稀有度，带保底与全局唯一记录"""
        pity_key = player_id if player_id is not None else "__global__"
        count = self._pity_counter.get(pity_key, 0) + 1

        if count >= int(self.config["pity_threshold"]):
            # 保底：强制 rare 及以上
            rarity = self._rng.choices(
                ["rare", "epic", "legendary"],
                weights=[RARITY_WEIGHTS["rare"], RARITY_WEIGHTS["epic"], RARITY_WEIGHTS["legendary"]],
            )[0]
        else:
            rarity = self._rng.choices(RARITIES, weights=[RARITY_WEIGHTS[r] for r in RARITIES])[0]

        if rarity != "common":
            self._pity_counter[pity_key] = 0
        else:
            self._pity_counter[pity_key] = count

        template_id, name = self._rng.choice(SKIN_TEMPLATES)
        skin_uid = uuid.uuid4().hex
        while skin_uid in self._skin_registry:  # 全局唯一保证
            skin_uid = uuid.uuid4().hex

        skin = {
            "skin_uid": skin_uid,
            "skin_id": template_id,
            "name": name,
            "rarity": rarity,
            "wear_value": round(self._rng.random(), 4),
            "pattern": self._rng.randint(1, 1000),
            "owner": player_id,
            "created_at": self._now(),
        }
        skin["wear_category"] = self.wear_calculation(skin["wear_value"])["category"]
        skin["price"] = self.calculate_price(skin)

        self._skin_registry[skin_uid] = skin  # 生成记录，防止重复生成/复制
        self._history.append({"event": "generate", "skin_uid": skin_uid, "rarity": rarity})

        if player_id is not None:
            result = self.add_to_inventory(player_id, skin)
            if not result["success"]:
                return result
        return skin

    def get_skin(self, skin_uid: str) -> Optional[Dict]:
        return self._skin_registry.get(skin_uid)

    def owner_of(self, skin_uid: str) -> Optional[str]:
        skin = self._skin_registry.get(skin_uid)
        return skin.get("owner") if skin else None

    # ------------------------------------------------------------------
    # 库存管理（容量 + 分类 + 重复检测 + 持久化）
    # ------------------------------------------------------------------
    def add_to_inventory(self, player_id: str, skin: Dict) -> Dict:
        """入库：容量限制 + 全局重复检测（同一皮肤不能出现在两个库存或重复入库）"""
        skin_uid = skin.get("skin_uid")
        if not skin_uid:
            return {"success": False, "error": "invalid_skin"}
        for owner, uids in self._inventories.items():
            if skin_uid in uids:
                return {"success": False, "error": "duplicate_skin", "owner": owner}
        inventory = self._inventories.setdefault(player_id, [])
        if len(inventory) >= int(self.config["inventory_capacity"]):
            return {"success": False, "error": "inventory_full"}
        inventory.append(skin_uid)
        skin["owner"] = player_id
        self._skin_registry[skin_uid] = skin
        self._save()
        return {"success": True, "skin_uid": skin_uid}

    def remove_from_inventory(self, player_id: str, skin_uid: str) -> Dict:
        inventory = self._inventories.get(player_id, [])
        if skin_uid not in inventory:
            return {"success": False, "error": "not_in_inventory"}
        inventory.remove(skin_uid)
        skin = self._skin_registry.get(skin_uid)
        if skin is not None:
            skin["owner"] = None
        self._save()
        return {"success": True}

    def inventory_management(self, player_id: str, category: Optional[str] = None):
        """查询库存：按磨损分类分组；指定 category 时返回该分类下的皮肤列表"""
        uids = self._inventories.get(player_id, [])
        skins = [self._skin_registry[u] for u in uids if u in self._skin_registry]
        if category is not None:
            return [s for s in skins if s.get("wear_category") == category]
        grouped: Dict[str, List[Dict]] = {}
        for skin in skins:
            grouped.setdefault(skin.get("wear_category", "未知"), []).append(skin)
        return grouped

    def inventory_count(self, player_id: str) -> int:
        return len(self._inventories.get(player_id, []))

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _save(self):
        path = self.config.get("storage_path")
        if not path:
            return
        data = {
            "inventories": {
                pid: [self._skin_registry[u] for u in uids if u in self._skin_registry]
                for pid, uids in self._inventories.items()
            },
            "balances": self._balances,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        path = self.config.get("storage_path")
        if not path or not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for pid, skins in data.get("inventories", {}).items():
            for skin in skins:
                uid = skin["skin_uid"]
                if uid in self._skin_registry:
                    continue  # 重复检测：同一皮肤只加载一次
                self._skin_registry[uid] = skin
                self._inventories.setdefault(pid, []).append(uid)
        self._balances.update({k: float(v) for k, v in data.get("balances", {}).items()})

    # ------------------------------------------------------------------
    # 市场上架（手续费 + 冷却 + 价格限制）
    # ------------------------------------------------------------------
    def market_listing(self, player_id: str, skin_uid: str, price: float) -> Dict:
        """上架皮肤：验证所有权、价格上下限、冷却，并收取手续费"""
        skin = self._skin_registry.get(skin_uid)
        if skin is None or skin.get("owner") != player_id:
            return {"success": False, "error": "not_owner"}
        if price < self.config["min_price"] or price > self.config["max_price"]:
            return {"success": False, "error": "price_out_of_range"}
        if any(l["skin_uid"] == skin_uid for l in self._listings.values()):
            return {"success": False, "error": "already_listed"}

        now = self._now()
        last = self._last_listing_action.get(player_id, 0.0)
        if now - last < float(self.config["listing_cooldown"]):
            return {"success": False, "error": "cooldown"}

        fee = round(price * float(self.config["listing_fee_rate"]), 2)
        if self.get_balance(player_id) < fee:
            return {"success": False, "error": "insufficient_funds"}
        self._balances[player_id] = self.get_balance(player_id) - fee

        self._listing_seq += 1
        listing_id = "L%d" % self._listing_seq
        listing = {
            "listing_id": listing_id,
            "skin_uid": skin_uid,
            "seller": player_id,
            "price": float(price),
            "fee": fee,
            "created_at": now,
        }
        self._listings[listing_id] = listing
        self._last_listing_action[player_id] = now
        self._history.append({"event": "list", "listing_id": listing_id, "fee": fee})
        self._save()
        return {"success": True, "listing": listing, "fee": fee}

    def market_delist(self, player_id: str, listing_id: str) -> Dict:
        """下架：同样受冷却限制，防止反复上下架刷排名"""
        listing = self._listings.get(listing_id)
        if listing is None:
            return {"success": False, "error": "listing_not_found"}
        if listing["seller"] != player_id:
            return {"success": False, "error": "not_owner"}
        now = self._now()
        last = self._last_listing_action.get(player_id, 0.0)
        if now - last < float(self.config["listing_cooldown"]):
            return {"success": False, "error": "cooldown"}
        del self._listings[listing_id]
        self._last_listing_action[player_id] = now
        self._history.append({"event": "delist", "listing_id": listing_id})
        return {"success": True}

    def get_listings(self) -> List[Dict]:
        return list(self._listings.values())

    # ------------------------------------------------------------------
    # 交易系统（所有权验证 + 冷却 + 记录）
    # ------------------------------------------------------------------
    def trade_system(self, seller_id: str, buyer_id: str, skin_uid: str, price: float) -> Dict:
        """玩家间交易：验证所有权、交易冷却、余额，完成后写入交易日志"""
        skin = self._skin_registry.get(skin_uid)
        if skin is None:
            return {"success": False, "error": "skin_not_found"}
        if skin.get("owner") != seller_id:
            return {"success": False, "error": "not_owner"}
        if any(l["skin_uid"] == skin_uid for l in self._listings.values()):
            return {"success": False, "error": "skin_listed"}

        now = self._now()
        for pid in (seller_id, buyer_id):
            if now - self._last_trade.get(pid, 0.0) < float(self.config["trade_cooldown"]):
                return {"success": False, "error": "cooldown", "player": pid}

        if self.get_balance(buyer_id) < price:
            return {"success": False, "error": "insufficient_funds"}
        buyer_inventory = self._inventories.setdefault(buyer_id, [])
        if len(buyer_inventory) >= int(self.config["inventory_capacity"]):
            return {"success": False, "error": "buyer_inventory_full"}

        self._balances[buyer_id] = self.get_balance(buyer_id) - price
        self._balances[seller_id] = self.get_balance(seller_id) + price
        self._inventories.get(seller_id, []).remove(skin_uid) if skin_uid in self._inventories.get(seller_id, []) else None
        buyer_inventory.append(skin_uid)
        skin["owner"] = buyer_id
        self._last_trade[seller_id] = now
        self._last_trade[buyer_id] = now

        record = {
            "seller": seller_id,
            "buyer": buyer_id,
            "skin_uid": skin_uid,
            "price": float(price),
            "timestamp": now,
        }
        self._trade_log.append(record)
        self._history.append({"event": "trade", **record})
        self._save()
        return {"success": True, "record": record}

    def get_trade_log(self) -> List[Dict]:
        return list(self._trade_log)
