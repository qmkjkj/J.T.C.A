from __future__ import annotations

import re

UNIVERSE = [
    # 白酒 / 食品饮料
    {"symbol": "600519.SS", "name": "贵州茅台", "cn": "贵州茅台", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "000858.SZ", "name": "五粮液", "cn": "五粮液", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "000568.SZ", "name": "泸州老窖", "cn": "泸州老窖", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "600809.SS", "name": "山西汾酒", "cn": "山西汾酒", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "600887.SS", "name": "伊利股份", "cn": "伊利股份", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "603288.SS", "name": "海天味业", "cn": "海天味业", "exchange": "SSE", "region": "CN", "kind": "股票"},
    # 金融
    {"symbol": "601318.SS", "name": "中国平安", "cn": "中国平安", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "600036.SS", "name": "招商银行", "cn": "招商银行", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "601398.SS", "name": "工商银行", "cn": "工商银行", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "601939.SS", "name": "建设银行", "cn": "建设银行", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "601288.SS", "name": "农业银行", "cn": "农业银行", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "601988.SS", "name": "中国银行", "cn": "中国银行", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "601628.SS", "name": "中国人寿", "cn": "中国人寿", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "600030.SS", "name": "中信证券", "cn": "中信证券", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "300059.SZ", "name": "东方财富", "cn": "东方财富", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    # 新能源 / 汽车
    {"symbol": "300750.SZ", "name": "宁德时代", "cn": "宁德时代", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "002594.SZ", "name": "比亚迪", "cn": "比亚迪", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "601127.SS", "name": "赛力斯", "cn": "赛力斯", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "600104.SS", "name": "上汽集团", "cn": "上汽集团", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "000625.SZ", "name": "长安汽车", "cn": "长安汽车", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "601012.SS", "name": "隆基绿能", "cn": "隆基绿能", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "300274.SZ", "name": "阳光电源", "cn": "阳光电源", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "002460.SZ", "name": "赣锋锂业", "cn": "赣锋锂业", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    # 医药
    {"symbol": "600276.SS", "name": "恒瑞医药", "cn": "恒瑞医药", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "300760.SZ", "name": "迈瑞医疗", "cn": "迈瑞医疗", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "603259.SS", "name": "药明康德", "cn": "药明康德", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "000538.SZ", "name": "云南白药", "cn": "云南白药", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    # 家电 / 消费
    {"symbol": "000333.SZ", "name": "美的集团", "cn": "美的集团", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "000651.SZ", "name": "格力电器", "cn": "格力电器", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "600690.SS", "name": "海尔智家", "cn": "海尔智家", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "601888.SS", "name": "中国中免", "cn": "中国中免", "exchange": "SSE", "region": "CN", "kind": "股票"},
    # 资源 / 能源 / 公用事业
    {"symbol": "601899.SS", "name": "紫金矿业", "cn": "紫金矿业", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "600028.SS", "name": "中国石化", "cn": "中国石化", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "601857.SS", "name": "中国石油", "cn": "中国石油", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "601088.SS", "name": "中国神华", "cn": "中国神华", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "600900.SS", "name": "长江电力", "cn": "长江电力", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "600309.SS", "name": "万华化学", "cn": "万华化学", "exchange": "SSE", "region": "CN", "kind": "股票"},
    # 制造 / 科技
    {"symbol": "600031.SS", "name": "三一重工", "cn": "三一重工", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "000725.SZ", "name": "京东方A", "cn": "京东方", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "002475.SZ", "name": "立讯精密", "cn": "立讯精密", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "002415.SZ", "name": "海康威视", "cn": "海康威视", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "002230.SZ", "name": "科大讯飞", "cn": "科大讯飞", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "688981.SS", "name": "中芯国际", "cn": "中芯国际", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "688111.SS", "name": "金山办公", "cn": "金山办公", "exchange": "SSE", "region": "CN", "kind": "股票"},
    {"symbol": "000002.SZ", "name": "万科A", "cn": "万科", "exchange": "SZSE", "region": "CN", "kind": "股票"},
    {"symbol": "600585.SS", "name": "海螺水泥", "cn": "海螺水泥", "exchange": "SSE", "region": "CN", "kind": "股票"},
    # ETF
    {"symbol": "510300.SS", "name": "沪深300ETF", "cn": "沪深300ETF", "exchange": "SSE", "region": "CN", "kind": "ETF"},
    {"symbol": "510050.SS", "name": "上证50ETF", "cn": "上证50ETF", "exchange": "SSE", "region": "CN", "kind": "ETF"},
    {"symbol": "159915.SZ", "name": "创业板ETF", "cn": "创业板ETF", "exchange": "SZSE", "region": "CN", "kind": "ETF"},
]

HK_UNIVERSE = [
    # 互联网 / 平台
    {"symbol": "00700.HK", "name": "腾讯控股", "cn": "腾讯控股", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "09988.HK", "name": "阿里巴巴-W", "cn": "阿里巴巴", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "03690.HK", "name": "美团-W", "cn": "美团", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "01810.HK", "name": "小米集团-W", "cn": "小米集团", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 200},
    {"symbol": "09618.HK", "name": "京东集团-SW", "cn": "京东集团", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 50},
    {"symbol": "09888.HK", "name": "百度集团-SW", "cn": "百度集团", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 50},
    {"symbol": "09999.HK", "name": "网易-S", "cn": "网易", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "01024.HK", "name": "快手-W", "cn": "快手", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "09961.HK", "name": "携程集团-S", "cn": "携程集团", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 50},
    {"symbol": "00780.HK", "name": "同程旅行", "cn": "同程旅行", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 400},
    {"symbol": "00268.HK", "name": "金蝶国际", "cn": "金蝶国际", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    # 金融
    {"symbol": "00005.HK", "name": "汇丰控股", "cn": "汇丰控股", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 400},
    {"symbol": "03988.HK", "name": "中国银行", "cn": "中国银行", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00939.HK", "name": "建设银行", "cn": "建设银行", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "01398.HK", "name": "工商银行", "cn": "工商银行", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "03968.HK", "name": "招商银行", "cn": "招商银行", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "02318.HK", "name": "中国平安", "cn": "中国平安", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "02628.HK", "name": "中国人寿", "cn": "中国人寿", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "01299.HK", "name": "友邦保险", "cn": "友邦保险", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 200},
    {"symbol": "00388.HK", "name": "香港交易所", "cn": "香港交易所", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "02388.HK", "name": "中银香港", "cn": "中银香港", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00011.HK", "name": "恒生银行", "cn": "恒生银行", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "02328.HK", "name": "中国财险", "cn": "中国财险", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "02601.HK", "name": "中国太保", "cn": "中国太保", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 200},
    {"symbol": "06030.HK", "name": "中信证券", "cn": "中信证券", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    # 电信 / 公用事业
    {"symbol": "00941.HK", "name": "中国移动", "cn": "中国移动", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00762.HK", "name": "中国联通", "cn": "中国联通", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "00728.HK", "name": "中国电信", "cn": "中国电信", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00002.HK", "name": "中电控股", "cn": "中电控股", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00003.HK", "name": "香港中华煤气", "cn": "香港中华煤气", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00006.HK", "name": "电能实业", "cn": "电能实业", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00066.HK", "name": "港铁公司", "cn": "港铁公司", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    # 地产 / 收租
    {"symbol": "00016.HK", "name": "新鸿基地产", "cn": "新鸿基地产", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00001.HK", "name": "长和", "cn": "长和", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "01113.HK", "name": "长实集团", "cn": "长实集团", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "01109.HK", "name": "华润置地", "cn": "华润置地", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00688.HK", "name": "中国海外发展", "cn": "中国海外发展", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00017.HK", "name": "新世界发展", "cn": "新世界发展", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00823.HK", "name": "领展房产基金", "cn": "领展房产基金", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    # 消费 / 博彩 / 餐饮
    {"symbol": "02020.HK", "name": "安踏体育", "cn": "安踏体育", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 200},
    {"symbol": "02331.HK", "name": "李宁", "cn": "李宁", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00291.HK", "name": "华润啤酒", "cn": "华润啤酒", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "02319.HK", "name": "蒙牛乳业", "cn": "蒙牛乳业", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "01044.HK", "name": "恒安国际", "cn": "恒安国际", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00322.HK", "name": "康师傅控股", "cn": "康师傅控股", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "00027.HK", "name": "银河娱乐", "cn": "银河娱乐", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "01928.HK", "name": "金沙中国有限公司", "cn": "金沙中国", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 400},
    {"symbol": "06618.HK", "name": "京东健康", "cn": "京东健康", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    # 医药
    {"symbol": "01177.HK", "name": "中国生物制药", "cn": "中国生物制药", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "02269.HK", "name": "药明生物", "cn": "药明生物", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "01093.HK", "name": "石药集团", "cn": "石药集团", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "02359.HK", "name": "药明康德", "cn": "药明康德", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "06160.HK", "name": "百济神州", "cn": "百济神州", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "01801.HK", "name": "信达生物", "cn": "信达生物", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    # 汽车 / 新能源
    {"symbol": "01211.HK", "name": "比亚迪股份", "cn": "比亚迪股份", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "09868.HK", "name": "小鹏汽车-W", "cn": "小鹏汽车", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "02015.HK", "name": "理想汽车-W", "cn": "理想汽车", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "09866.HK", "name": "蔚来-SW", "cn": "蔚来", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "02333.HK", "name": "长城汽车", "cn": "长城汽车", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00175.HK", "name": "吉利汽车", "cn": "吉利汽车", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00968.HK", "name": "信义光能", "cn": "信义光能", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "00868.HK", "name": "信义玻璃", "cn": "信义玻璃", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    # 半导体 / 硬件
    {"symbol": "00981.HK", "name": "中芯国际", "cn": "中芯国际", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "01347.HK", "name": "华虹半导体", "cn": "华虹半导体", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00992.HK", "name": "联想集团", "cn": "联想集团", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "00285.HK", "name": "比亚迪电子", "cn": "比亚迪电子", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "02382.HK", "name": "舜宇光学科技", "cn": "舜宇光学科技", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00522.HK", "name": "ASMPT", "cn": "ASMPT", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 100},
    {"symbol": "02018.HK", "name": "瑞声科技", "cn": "瑞声科技", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    # 能源 / 资源 / 航运
    {"symbol": "00883.HK", "name": "中国海洋石油", "cn": "中国海洋石油", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "00857.HK", "name": "中国石油股份", "cn": "中国石油股份", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "00386.HK", "name": "中国石油化工股份", "cn": "中国石油化工股份", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "01088.HK", "name": "中国神华", "cn": "中国神华", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "00902.HK", "name": "华能国际电力股份", "cn": "华能国际电力股份", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "00916.HK", "name": "龙源电力", "cn": "龙源电力", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "02899.HK", "name": "紫金矿业", "cn": "紫金矿业", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    {"symbol": "02600.HK", "name": "中国铝业", "cn": "中国铝业", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 2000},
    {"symbol": "01818.HK", "name": "招金矿业", "cn": "招金矿业", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 500},
    {"symbol": "01919.HK", "name": "中远海控", "cn": "中远海控", "exchange": "HKEX", "region": "HK", "kind": "股票", "lot_size": 1000},
    # ETF
    {"symbol": "02800.HK", "name": "盈富基金", "cn": "盈富基金", "exchange": "HKEX", "region": "HK", "kind": "ETF", "lot_size": 500},
    {"symbol": "02828.HK", "name": "恒生中国企业", "cn": "恒生中国企业", "exchange": "HKEX", "region": "HK", "kind": "ETF", "lot_size": 200},
    {"symbol": "03033.HK", "name": "南方恒生科技", "cn": "南方恒生科技", "exchange": "HKEX", "region": "HK", "kind": "ETF", "lot_size": 200},
]

HK_INDEX_SYMBOLS = {"^HSI", "^HSCE", "^HSTECH"}

_BY_SYMBOL = {item["symbol"].upper(): item for item in UNIVERSE + HK_UNIVERSE}

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.\-]{0,14}$")


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper().replace(" ", "")
    if re.fullmatch(r"\d{6}", symbol):
        if symbol[0] in {"5", "6", "9"}:
            return f"{symbol}.SS"
        if symbol[0] in {"4", "8"}:
            return f"{symbol}.BJ"
        return f"{symbol}.SZ"
    # 港股：支持 700 / 0700 / 00700 / 00700.HK / HK00700 等写法。
    match = re.fullmatch(r"(\d{1,5})\.HK", symbol)
    if match:
        return f"{match.group(1).zfill(5)}.HK"
    match = re.fullmatch(r"(?:HK)?\.?(\d{1,5})", symbol)
    if match:
        return f"{match.group(1).zfill(5)}.HK"
    return symbol


def is_valid_symbol(value: str) -> bool:
    return bool(SYMBOL_PATTERN.fullmatch(normalize_symbol(value)))


def lookup(symbol: str) -> dict | None:
    return _BY_SYMBOL.get(normalize_symbol(symbol))


def display_name(symbol: str) -> str:
    item = lookup(symbol)
    return item["name"] if item else normalize_symbol(symbol)


def lot_size(symbol: str) -> int:
    item = lookup(symbol)
    if item and item.get("lot_size"):
        try:
            return max(1, int(item["lot_size"]))
        except (TypeError, ValueError):
            pass
    return 100


def platform_of_symbol(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    if normalized.endswith(".HK") or normalized in HK_INDEX_SYMBOLS:
        return "HK"
    return "CN"


def platform_of_symbols(symbols: list[str]) -> str:
    for symbol in symbols:
        if platform_of_symbol(symbol) == "HK":
            return "HK"
    return "CN"


def search(query: str, limit: int = 8, platform: str = "CN") -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    region = "HK" if (platform or "").strip().upper() == "HK" else "CN"
    pool = HK_UNIVERSE if region == "HK" else UNIVERSE
    scored: list[tuple[int, dict]] = []
    for item in pool:
        symbol = item["symbol"].lower()
        code = symbol.split(".")[0]
        name = item["name"].lower()
        cn = item["cn"].lower()
        haystack = f"{symbol} {code} {name} {cn} {item['exchange'].lower()}"
        if q not in haystack:
            continue
        if symbol == q or code == q:
            score = 0
        elif symbol.startswith(q) or code.startswith(q):
            score = 1
        elif cn.startswith(q):
            score = 2
        elif name.startswith(q):
            score = 3
        else:
            score = 4
        scored.append((score, item))
    scored.sort(key=lambda pair: (pair[0], pair[1]["symbol"]))
    return [item for _, item in scored[:limit]]
