"""
武器皮肤与市场交易系统 - 验收测试

运行方式：python -m pytest tests/test_skin_market.py -q
共 15 个测试用例
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from economy.skin_market import SkinMarket, RARITIES, RARITY_BASE_PRICE


def make_system(**overrides):
    config = {"seed": 42, "listing_cooldown": 0.0, "trade_cooldown": 0.0}
    config.update(overrides)
    return SkinMarket(config)


class TestSkinMarket:
    """武器皮肤与市场交易系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化"""
        self.system = make_system()

    def test_case_01(self):
        """皮肤生成：完整随机皮肤ID/磨损值/图案模板/稀有度"""
        skin = self.system.generate_skin()
        assert skin["skin_id"] >= 1
        assert 0.0 <= skin["wear_value"] <= 1.0
        assert 1 <= skin["pattern"] <= 1000
        assert skin["rarity"] in RARITIES
        assert skin["skin_uid"]
        assert skin["wear_category"]

    def test_case_02(self):
        """磨损计算：五种磨损分类 + 具体数值"""
        cases = [
            (0.05, "崭新出厂"),
            (0.10, "略有磨损"),
            (0.20, "久经沙场"),
            (0.40, "破损不堪"),
            (0.90, "战痕累累"),
        ]
        for value, expected in cases:
            result = self.system.wear_calculation(value)
            assert result["category"] == expected
            assert result["wear_value"] == value
            assert 0 < result["price_multiplier"] <= 1.0

    def test_case_03(self):
        """磨损影响价格：战痕累累价格 < 崭新出厂价格"""
        factory_new = {"rarity": "rare", "wear_value": 0.01}
        battle_scarred = {"rarity": "rare", "wear_value": 0.90}
        assert self.system.calculate_price(battle_scarred) < self.system.calculate_price(factory_new)
        assert self.system.calculate_price(factory_new) == RARITY_BASE_PRICE["rare"]

    def test_case_04(self):
        """保底机制：连续开箱达到保底次数必出稀有及以上"""
        system = make_system(seed=7, inventory_capacity=1000)
        skins = [system.generate_skin("p1") for _ in range(200)]
        for i in range(0, len(skins), 10):
            window = skins[i:i + 10]
            assert any(s["rarity"] != "common" for s in window)
        forced = make_system(seed=7, pity_threshold=1)
        assert forced.generate_skin("p2")["rarity"] in ("rare", "epic", "legendary")

    def test_case_05(self):
        """皮肤唯一记录：生成的每个皮肤都有唯一UID并登记"""
        skins = [self.system.generate_skin() for _ in range(200)]
        uids = [s["skin_uid"] for s in skins]
        assert len(set(uids)) == len(uids)
        for uid in uids:
            assert self.system.get_skin(uid) is not None

    def test_case_06(self):
        """市场上架：收取手续费"""
        self.system.set_balance("p1", 1000.0)
        skin = self.system.generate_skin("p1")
        result = self.system.market_listing("p1", skin["skin_uid"], 100.0)
        assert result["success"]
        assert result["fee"] == 5.0
        assert self.system.get_balance("p1") == 995.0

    def test_case_07(self):
        """市场上架：冷却期内禁止再次上架/下架"""
        system = make_system(listing_cooldown=60.0)
        skin1 = system.generate_skin("p1")
        skin2 = system.generate_skin("p1")
        first = system.market_listing("p1", skin1["skin_uid"], 10.0)
        assert first["success"]
        second = system.market_listing("p1", skin2["skin_uid"], 10.0)
        assert not second["success"] and second["error"] == "cooldown"
        delist = system.market_delist("p1", first["listing"]["listing_id"])
        assert not delist["success"] and delist["error"] == "cooldown"

    def test_case_08(self):
        """市场上架：价格上下限校验"""
        skin = self.system.generate_skin("p1")
        assert not self.system.market_listing("p1", skin["skin_uid"], 0.01)["success"]
        assert not self.system.market_listing("p1", skin["skin_uid"], 1_000_000.0)["success"]
        assert self.system.market_listing("p1", skin["skin_uid"], 50.0)["success"]

    def test_case_09(self):
        """市场上架/下架：挂单进入市场，下架后移除"""
        skin = self.system.generate_skin("p1")
        result = self.system.market_listing("p1", skin["skin_uid"], 50.0)
        listing_id = result["listing"]["listing_id"]
        assert any(l["listing_id"] == listing_id for l in self.system.get_listings())
        assert self.system.market_delist("p1", listing_id)["success"]
        assert all(l["listing_id"] != listing_id for l in self.system.get_listings())

    def test_case_10(self):
        """交易系统：验证物品所有权，不能交易别人的皮肤"""
        skin = self.system.generate_skin("p1")
        result = self.system.trade_system("p2", "p3", skin["skin_uid"], 10.0)
        assert not result["success"] and result["error"] == "not_owner"
        assert self.system.owner_of(skin["skin_uid"]) == "p1"

    def test_case_11(self):
        """交易系统：交易冷却防止无限刷交易量"""
        system = make_system(trade_cooldown=60.0)
        skin1 = system.generate_skin("seller")
        skin2 = system.generate_skin("seller")
        assert system.trade_system("seller", "buyer", skin1["skin_uid"], 10.0)["success"]
        result = system.trade_system("seller", "buyer", skin2["skin_uid"], 10.0)
        assert not result["success"] and result["error"] == "cooldown"

    def test_case_12(self):
        """交易系统：交易完成后有完整日志记录"""
        skin = self.system.generate_skin("seller")
        result = self.system.trade_system("seller", "buyer", skin["skin_uid"], 88.0)
        assert result["success"]
        log = self.system.get_trade_log()
        assert len(log) == 1
        record = log[0]
        assert record["seller"] == "seller"
        assert record["buyer"] == "buyer"
        assert record["skin_uid"] == skin["skin_uid"]
        assert record["price"] == 88.0
        assert "timestamp" in record

    def test_case_13(self):
        """库存管理：容量限制与分类查询"""
        system = make_system(inventory_capacity=2, seed=3)
        first = system.generate_skin("p1")
        second = system.generate_skin("p1")
        assert system.inventory_count("p1") == 2
        third = system.generate_skin("p1")
        assert not third["success"] and third["error"] == "inventory_full"
        grouped = system.inventory_management("p1")
        category = first["wear_category"]
        assert category in grouped
        filtered = system.inventory_management("p1", category=category)
        assert first["skin_uid"] in [s["skin_uid"] for s in filtered]

    def test_case_14(self):
        """库存管理：重复检测，同一皮肤不能出现在多个库存或重复入库"""
        skin = self.system.generate_skin("p1")
        dup = self.system.add_to_inventory("p2", skin)
        assert not dup["success"] and dup["error"] == "duplicate_skin"
        dup_same = self.system.add_to_inventory("p1", skin)
        assert not dup_same["success"] and dup_same["error"] == "duplicate_skin"

    def test_case_15(self, tmp_path):
        """库存管理：持久化，重启后库存不丢失且重复皮肤只恢复一次"""
        path = str(tmp_path / "inventory.json")
        system = make_system(storage_path=path)
        skin = system.generate_skin("p1")
        assert os.path.exists(path)

        reloaded = make_system(storage_path=path)
        assert reloaded.inventory_count("p1") == 1
        restored = reloaded.inventory_management("p1")
        all_skins = [s for group in restored.values() for s in group]
        assert len({s["skin_uid"] for s in all_skins}) == len(all_skins)
        assert skin["skin_uid"] in [s["skin_uid"] for s in all_skins]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
