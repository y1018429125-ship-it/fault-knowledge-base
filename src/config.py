# Core configuration for 故障知识库

# Data paths
REPORT_DIR = "./故障报告"
QDRANT_PATH = "./qdrant_db"
LOG_DIR = "./logs"

# File server
FILE_SERVER_HOST = "localhost"
FILE_SERVER_PORT = 18080
FILE_SERVER_URL = f"http://{FILE_SERVER_HOST}:{FILE_SERVER_PORT}"

# HTTP API server (external projects call the QA pipeline)
API_HOST = "0.0.0.0"
API_PORT = 8503

# Embedding service (bge-m3, OpenAI Compatible)
EMBEDDING_ENDPOINT = "http://172.18.179.2:20013/v1/embeddings"
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIMENSION = 1024
EMBEDDING_BATCH_SIZE = 16

# LLM service (gemma-4-31B-it, OpenAI Compatible)
LLM_ENDPOINT = "http://172.18.179.2:20017/v1/chat/completions"
LLM_MODEL = "gemma-4-31B-it"
LLM_MAX_TOKENS = 8192
LLM_TIMEOUT = 300
LLM_TEMPERATURE = 0.1

# Qdrant
COLLECTION_NAME = "fault_reports"
VECTOR_DISTANCE = "Cosine"

# Chunking
CHUNK_MAX_CHARS = 4000
CHUNK_OVERLAP_CHARS = 200

# Retrieval
RETRIEVAL_TOP_K = 10
RETRIEVAL_SCORE_THRESHOLD = 0.5

# Routing
ROUTER_SIMILARITY_THRESHOLD = 0.75

# Province aliases: map various operator names to province
PROVINCE_ALIASES = {
    "北京": "北京",
    "天津": "天津",
    "河北": "河北",
    "冀北": "冀北",
    "山西": "山西",
    "山东": "山东",
    "河南": "河南",
    "辽宁": "辽宁",
    "吉林": "吉林",
    "黑龙江": "黑龙江",
    "蒙东": "蒙东",
    "内蒙古": "内蒙古",
    "江苏": "江苏",
    "浙江": "浙江",
    "安徽": "安徽",
    "福建": "福建",
    "上海": "上海",
    "湖北": "湖北",
    "湖南": "湖南",
    "江西": "江西",
    "四川": "四川",
    "重庆": "重庆",
    "陕西": "陕西",
    "甘肃": "甘肃",
    "青海": "青海",
    "宁夏": "宁夏",
    "新疆": "新疆",
    "西藏": "西藏",
    "广东": "广东",
    "广西": "广西",
    "云南": "云南",
    "贵州": "贵州",
    "海南": "海南",
}

# Voltage normalization: regex pattern -> canonical form
VOLTAGE_PATTERNS = [
    (r"±?1100(?:千伏|kV)?", "1100kV"),
    (r"±?1000(?:千伏|kV)?", "1000kV"),
    (r"±?800(?:千伏|kV)?", "800kV"),
    (r"±?750(?:千伏|kV)?", "750kV"),
    (r"±?500(?:千伏|kV)?", "500kV"),
    (r"±?400(?:千伏|kV)?", "400kV"),
    (r"±?330(?:千伏|kV)?", "330kV"),
    (r"±?320(?:千伏|kV)?", "320kV"),
    (r"±?220(?:千伏|kV)?", "220kV"),
    (r"±?110(?:千伏|kV)?", "110kV"),
]

# Fault type keywords
# 注意：绕击/反击不是独立标签——二者是雷击的细分，提取时经 metadata 同义词规则
# 统一归并为"雷击"，细分区分由事件卡"雷击细分"字段承担（不进元数据标签体系）。
# 同理：鸟粪是鸟害的细分，统一归并为"鸟害"（查询侧问"鸟粪"经同义词规则归一，
# 细分表述保留在事件卡正文中）。
FAULT_TYPES = [
    "雷击",
    "异物短路",
    "风偏",
    "山火",
    "鸟害",
    "舞动",
    "冰害",
    "冰闪",
    "脱冰跳跃",
    "雪闪",
    "断线",
    "外力破坏",
]

# Time granularity defaults
DEFAULT_YEAR = 2026
