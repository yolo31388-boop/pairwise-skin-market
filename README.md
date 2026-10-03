# 武器皮肤与市场交易系统

## 项目描述

武器皮肤与市场交易系统的bug修复项目。核心模块 `economy/skin_market.py` 存在多个已知bug，需要修复后使测试全部通过。

## 已知问题

- 皮肤生成只随机ID无磨损无稀有度无保底
- 磨损度只有崭新出厂一种不影响价格
- 市场上架无手续费无冷却无价格限制
- 交易系统不验证所有权无冷却无记录
- 库存无容量无分类无重复检测不保存

## 项目结构

```
├── economy/skin_market.py       # 核心模块（带bug）
├── tests/test_skin_market.py    # 验收测试（红态）
├── pyproject.toml          # 项目配置
└── README.md               # 说明文档
```

## 运行测试

```bash
python -m pytest tests/test_skin_market.py -q
```

修复目标：所有 15 个测试全部通过。

## 技术要求

- 纯Python标准库，不引入第三方依赖
- 不修改测试文件
- 保持现有API接口不变
- 修复所有已知bug
