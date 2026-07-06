"""选股后走势归因研究 - 配置项"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

# 数据来源
SELECTIONS_FILE = PROJECT_ROOT / 'stock_data' / 'selections.json'

# 缓存与产出
CACHE_DIR = ROOT / 'cache'
OUTPUT_DIR = ROOT / 'output'
LOG_FILE = OUTPUT_DIR / 'pipeline.log'

CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# 时间窗口
PRE_DAYS = 60   # 入选日前用于计算特征
POST_DAYS = 30  # 入选日后用于打标

# 走势打标阈值（首轮跑后调整：放宽 strong/oscillate 边界以扩大样本）
LABEL_THRESHOLDS = {
    'strong': {'max_dd_lt': 0.08, 'ret_30_gt': 0.08},
    'breakdown': {'stop_loss': -0.10},
    'oscillate': {'abs_ret_lt': 0.08, 'max_dd_range': (0.0, 0.08)},
}

# 时间切分（验证稳定性）— 前段样本太少，下移到 5/15
SPLIT_DATE = '2026-05-15'

# 决策树
TREE_MAX_DEPTH = 3
TREE_MIN_SAMPLES_LEAF = 10
