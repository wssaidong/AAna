#!/usr/bin/env python3
"""
A股股票筛选器
根据多种财务指标筛选符合条件的股票

依赖: pip install akshare pandas numpy
"""

import argparse
import json
import sys
import time
from datetime import datetime
from typing import List, Dict
from functools import wraps

try:
    import akshare as ak
    import pandas as pd
    import numpy as np
except ImportError:
    print("错误: 请先安装依赖库")
    print("pip install akshare pandas numpy")
    sys.exit(1)


def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """网络请求重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        print(f"  重试 ({attempt + 1}/{max_retries})...")
                        time.sleep(delay * (attempt + 1))
            raise last_error
        return wrapper
    return decorator


INDEX_CODE_MAP = {
    "hs300": "000300",
    "zz500": "000905",
    "zz1000": "000852",
    "cyb": "399006",
    "kcb": "000688"
}


class StockScreener:
    """股票筛选器"""

    def __init__(self):
        self.all_stocks_data = None

    def load_stock_data(self, scope: str = "hs300", custom_codes: List[str] = None) -> pd.DataFrame:
        """加载股票数据"""
        print(f"正在加载股票数据 (范围: {scope})...")

        try:
            if scope == "all":
                df = ak.stock_zh_a_spot_em()
            elif scope in INDEX_CODE_MAP:
                df = self._get_index_stocks_data(INDEX_CODE_MAP[scope])
            elif scope.startswith("custom:") or custom_codes:
                codes = custom_codes or scope.replace("custom:", "").split(",")
                df = self._get_custom_stocks_data(codes)
            else:
                df = ak.stock_zh_a_spot_em()

            self.all_stocks_data = df
            print(f"已加载 {len(df)} 只股票数据")
            return df

        except Exception as e:
            print(f"加载数据失败: {e}")
            return pd.DataFrame()

    @retry_on_failure(max_retries=3, delay=2.0)
    def _get_all_stocks_realtime(self) -> pd.DataFrame:
        """获取全部A股实时数据（带重试）"""
        return ak.stock_zh_a_spot_em()

    @retry_on_failure(max_retries=3, delay=2.0)
    def _get_index_constituents(self, index_code: str) -> list:
        """获取指数成分股列表（带重试）"""
        df = ak.index_stock_cons(symbol=index_code)
        return df['品种代码'].tolist()

    def _get_index_stocks_data(self, index_code: str) -> pd.DataFrame:
        """获取指数成分股数据"""
        try:
            # 获取成分股列表
            print(f"  获取指数 {index_code} 成分股...")
            codes = self._get_index_constituents(index_code)
            print(f"  成分股数量: {len(codes)}")

            # 获取实时数据
            print("  获取实时行情...")
            all_stocks = self._get_all_stocks_realtime()
            df = all_stocks[all_stocks['代码'].isin(codes)]
            return df
        except Exception as e:
            print(f"获取指数成分股失败: {e}")
            return pd.DataFrame()

    def _get_custom_stocks_data(self, codes: List[str]) -> pd.DataFrame:
        """获取自定义股票列表数据"""
        try:
            all_stocks = self._get_all_stocks_realtime()
            df = all_stocks[all_stocks['代码'].isin(codes)]
            return df
        except Exception as e:
            print(f"获取自定义股票数据失败: {e}")
            return pd.DataFrame()

    def _is_banned_board(self, code: str) -> bool:
        """检查是否属于不推荐的板块（科创板688/8开头、老三板8开头 - 过滤；创业板300/301开头 - 保留但风险提示）"""
        if not code:
            return False
        code_str = str(code)
        # 科创板: 688开头 或 老三板: 8开头（过滤）
        if code_str.startswith('688') or code_str.startswith('8'):
            return True
        # 创业板: 300开头 或 301开头（保留，不在此过滤）
        return False

    def _is_gem_board(self, code: str) -> bool:
        """检查是否属于创业板（300/301开头 - 保留但风险提示）"""
        if not code:
            return False
        code_str = str(code)
        return code_str.startswith('300') or code_str.startswith('301')

    def _apply_numeric_filter(self, df: pd.DataFrame, column: str,
                               min_val: float = None, max_val: float = None) -> pd.DataFrame:
        """应用数值筛选条件"""
        if column not in df.columns:
            return df

        numeric_col = pd.to_numeric(df[column], errors='coerce')
        if min_val is not None:
            df = df[numeric_col >= min_val]
        if max_val is not None:
            df = df[numeric_col <= max_val]
        return df

    def _find_column(self, df: pd.DataFrame, candidates: List[str]) -> str:
        """从候选列名中找到存在的列"""
        for col in candidates:
            if col in df.columns:
                return col
        return None

    def apply_filters(self, df: pd.DataFrame, filters: Dict) -> pd.DataFrame:
        """应用筛选条件"""
        filtered = df.copy()

        # 科创板/创业板过滤（默认排除）
        if filters.get('exclude_banned_board', True):
            before_count = len(filtered)
            filtered = filtered[~filtered['代码'].apply(self._is_banned_board)]
            after_count = len(filtered)
            if before_count > after_count:
                print(f"  排除科创板/老三板: {before_count - after_count} 只")

        # PE筛选（排除负PE）
        pe_min = filters.get('pe_min')
        if pe_min is None or pe_min < 0:
            pe_min = 0.0001  # 排除负数和零PE
        filtered = self._apply_numeric_filter(
            filtered, '市盈率-动态',
            min_val=pe_min,
            max_val=filters.get('pe_max')
        )

        # PB筛选
        filtered = self._apply_numeric_filter(
            filtered, '市净率',
            min_val=filters.get('pb_min'),
            max_val=filters.get('pb_max')
        )

        # ROE筛选
        if filters.get('roe_min') is not None:
            roe_col = self._find_column(filtered, ['净资产收益率', 'ROE', '加权净资产收益率'])
            if roe_col:
                filtered = self._apply_numeric_filter(filtered, roe_col, min_val=filters['roe_min'])

        # 资产负债率筛选
        filtered = self._apply_numeric_filter(
            filtered, '资产负债率',
            max_val=filters.get('debt_ratio_max')
        )

        # 量比筛选（异动检测）
        if filters.get('volume_ratio_min') is not None or filters.get('volume_ratio_max') is not None:
            filtered = self._apply_numeric_filter(
                filtered, '量比',
                min_val=filters.get('volume_ratio_min'),
                max_val=filters.get('volume_ratio_max')
            )

        # 主力净流入占比筛选
        if filters.get('main_net_ratio_min') is not None or filters.get('main_net_ratio_max') is not None:
            main_col = self._find_column(filtered, ['主力净流入占比', '主力净流入占总成交额比例'])
            if main_col:
                filtered = self._apply_numeric_filter(
                    filtered, main_col,
                    min_val=filters.get('main_net_ratio_min'),
                    max_val=filters.get('main_net_ratio_max')
                )

        # RSI极端值筛选
        if filters.get('rsi_max') is not None:
            rsi_col = self._find_column(filtered, ['RSI', 'RSI_14'])
            if rsi_col:
                filtered = self._apply_numeric_filter(filtered, rsi_col, max_val=filters['rsi_max'])
        if filters.get('rsi_min') is not None:
            rsi_col = self._find_column(filtered, ['RSI', 'RSI_14'])
            if rsi_col:
                filtered = self._apply_numeric_filter(filtered, rsi_col, min_val=filters['rsi_min'])

        # 趋势过滤（排除下跌趋势：MA5<MA20 或近20日涨幅<-10%）
        if filters.get('exclude_downtrend'):
            before_count = len(filtered)
            ma5_col = self._find_column(filtered, ['MA5', 'ma5'])
            ma20_col = self._find_column(filtered, ['MA20', 'ma20'])
            change20_col = self._find_column(filtered, ['20日涨跌幅', '近20日涨幅', '涨幅20日'])
            # 过滤MA5<MA20
            if ma5_col and ma20_col:
                filtered = filtered[~(pd.to_numeric(filtered[ma5_col], errors='coerce') <
                                     pd.to_numeric(filtered[ma20_col], errors='coerce'))]
            # 过滤近20日涨幅<-10%
            if change20_col:
                filtered = filtered[~(pd.to_numeric(filtered[change20_col], errors='coerce') < -10)]
            after_count = len(filtered)
            if before_count > after_count:
                print(f"  排除下跌趋势: {before_count - after_count} 只")

        # 总市值筛选（转换为亿）
        if '总市值' in filtered.columns:
            if filters.get('market_cap_min') is not None or filters.get('market_cap_max') is not None:
                filtered['总市值_亿'] = pd.to_numeric(filtered['总市值'], errors='coerce') / 1e8
                filtered = self._apply_numeric_filter(
                    filtered, '总市值_亿',
                    min_val=filters.get('market_cap_min'),
                    max_val=filters.get('market_cap_max')
                )

        return filtered

    def _get_numeric_value(self, row: pd.Series, column: str) -> float:
        """从行中获取数值，无效返回 NaN"""
        return pd.to_numeric(row.get(column, np.nan), errors='coerce')

    def calculate_score(self, row: pd.Series, weights: Dict = None) -> float:
        """计算综合评分 (0-100)
        
        Args:
            row: 股票数据行
            weights: 评分权重配置，格式:
                {
                    'pe': 15,      # PE权重（默认15）
                    'pb': 10,      # PB权重（默认10）
                    'roe': 15,     # ROE权重（默认15）
                    'change': 5,   # 涨跌幅权重（默认5）
                    'volume_ratio': 5,   # 量比权重（新增）
                    'main_net_ratio': 5, # 主力净流入占比权重（新增）
                    'rsi': 5              # RSI权重（新增）
                }
        """
        # 默认权重
        default_weights = {
            'pe': 15,
            'pb': 10,
            'roe': 15,
            'change': 5,
            'volume_ratio': 5,
            'main_net_ratio': 5,
            'rsi': 5
        }
        if weights:
            default_weights.update(weights)
        w = default_weights

        score = 50

        try:
            # PE评分 (越低越好, 负数除外)
            pe = self._get_numeric_value(row, '市盈率-动态')
            if not np.isnan(pe) and pe > 0:
                if pe < 10:
                    score += w['pe']
                elif pe < 15:
                    score += w['pe'] * 0.7
                elif pe < 20:
                    score += w['pe'] * 0.3
                elif pe > 50:
                    score -= w['pe'] * 0.7

            # PB评分
            pb = self._get_numeric_value(row, '市净率')
            if not np.isnan(pb) and pb > 0:
                if 0.5 < pb < 1.5:
                    score += w['pb']
                elif 1.5 <= pb < 3:
                    score += w['pb'] * 0.5
                elif pb > 5:
                    score -= w['pb'] * 0.5

            # ROE评分
            roe_col = self._find_column(row.index.to_frame(), ['净资产收益率', 'ROE', '加权净资产收益率'])
            if roe_col:
                roe = self._get_numeric_value(row, roe_col)
                if not np.isnan(roe):
                    if roe > 20:
                        score += w['roe']
                    elif roe > 15:
                        score += w['roe'] * 0.7
                    elif roe > 10:
                        score += w['roe'] * 0.3
                    elif roe < 5:
                        score -= w['roe'] * 0.3

            # 涨跌幅评分 (下跌可能是机会)
            change = self._get_numeric_value(row, '涨跌幅')
            if not np.isnan(change):
                if -5 < change < 0:
                    score += w['change'] * 0.6
                elif change < -5:
                    score += w['change']

            # 量比评分（异动检测，越高可能越活跃）
            volume_ratio = self._get_numeric_value(row, '量比')
            if not np.isnan(volume_ratio):
                if 1.5 <= volume_ratio <= 3:
                    score += w['volume_ratio'] * 0.5
                elif volume_ratio > 3:
                    score += w['volume_ratio'] * 0.8
                elif volume_ratio < 0.5:
                    score -= w['volume_ratio'] * 0.3

            # 主力净流入占比评分
            main_col = self._find_column(row.index.to_frame(), ['主力净流入占比', '主力净流入占总成交额比例'])
            if main_col:
                main_net_ratio = self._get_numeric_value(row, main_col)
                if not np.isnan(main_net_ratio):
                    if main_net_ratio > 10:
                        score += w['main_net_ratio']
                    elif main_net_ratio > 5:
                        score += w['main_net_ratio'] * 0.6
                    elif main_net_ratio < -10:
                        score -= w['main_net_ratio'] * 0.5

            # RSI评分（极端值过滤参考）
            rsi_col = self._find_column(row.index.to_frame(), ['RSI', 'RSI_14'])
            if rsi_col:
                rsi = self._get_numeric_value(row, rsi_col)
                if not np.isnan(rsi):
                    if 40 <= rsi <= 60:
                        score += w['rsi'] * 0.3  # 中性区间
                    elif rsi < 30:
                        score += w['rsi'] * 0.5  # 超卖，可能是机会
                    elif rsi > 70:
                        score -= w['rsi'] * 0.3  # 超买，风险

        except Exception:
            pass

        return max(0, min(100, score))

    def screen(self, scope: str = "hs300", filters: Dict = None,
              sort_by: str = "score", top_n: int = None,
              score_weights: Dict = None) -> List[Dict]:
        """执行筛选
        
        Args:
            scope: 筛选范围
            filters: 筛选条件字典
            sort_by: 排序方式
            top_n: 返回前N只股票
            score_weights: 评分权重配置，格式:
                {
                    'pe': 15, 'pb': 10, 'roe': 15, 'change': 5,
                    'volume_ratio': 5, 'main_net_ratio': 5, 'rsi': 5
                }
        """
        # 加载数据
        if scope.startswith("custom:"):
            codes = scope.replace("custom:", "").split(",")
            df = self.load_stock_data(scope="custom", custom_codes=codes)
        else:
            df = self.load_stock_data(scope=scope)

        if df.empty:
            return []

        # 应用筛选条件
        if filters:
            df = self.apply_filters(df, filters)

        if df.empty:
            return []

        # 计算评分
        df['评分'] = df.apply(lambda row: self.calculate_score(row, score_weights), axis=1)

        # 排序
        if sort_by == "score":
            df = df.sort_values('评分', ascending=False)
        elif sort_by == "pe":
            pe_col = '市盈率-动态' if '市盈率-动态' in df.columns else None
            if pe_col:
                df = df.sort_values(pe_col, ascending=True)
        elif sort_by == "pb":
            if '市净率' in df.columns:
                df = df.sort_values('市净率', ascending=True)
        elif sort_by == "market_cap":
            if '总市值' in df.columns:
                df = df.sort_values('总市值', ascending=False)

        # 限制数量
        if top_n:
            df = df.head(top_n)

        # 转换为结果列表
        results = []
        for _, row in df.iterrows():
            result = {
                "代码": row.get('代码', ''),
                "名称": row.get('名称', ''),
                "最新价": row.get('最新价', ''),
                "涨跌幅": row.get('涨跌幅', ''),
                "市盈率": row.get('市盈率-动态', ''),
                "市净率": row.get('市净率', ''),
                "总市值(亿)": round(float(row.get('总市值', 0)) / 100000000, 2) if row.get('总市值') else '',
                "评分": row.get('评分', 50)
            }
            results.append(result)

        return results


def main():
    parser = argparse.ArgumentParser(description="A股股票筛选器")
    parser.add_argument("--scope", type=str, default="hs300",
                       help="筛选范围: all/hs300/zz500/zz1000/cyb/kcb/custom:代码1,代码2")
    parser.add_argument("--pe-max", type=float, help="最大PE")
    parser.add_argument("--pe-min", type=float, help="最小PE")
    parser.add_argument("--pb-max", type=float, help="最大PB")
    parser.add_argument("--pb-min", type=float, help="最小PB")
    parser.add_argument("--roe-min", type=float, help="最小ROE (%%)")
    parser.add_argument("--debt-ratio-max", type=float, help="最大资产负债率 (%%)")
    parser.add_argument("--dividend-min", type=float, help="最小股息率 (%%)")
    parser.add_argument("--market-cap-min", type=float, help="最小市值 (亿)")
    parser.add_argument("--market-cap-max", type=float, help="最大市值 (亿)")
    parser.add_argument("--sort-by", type=str, default="score",
                       choices=["score", "pe", "pb", "market_cap"],
                       help="排序方式")
    parser.add_argument("--top", type=int, default=50, help="返回前N只股票")
    parser.add_argument("--output", type=str, help="输出文件路径 (JSON)")
    parser.add_argument("--volume-ratio-min", type=float, help="最小量比（异动检测）")
    parser.add_argument("--volume-ratio-max", type=float, help="最大量比")
    parser.add_argument("--main-net-ratio-min", type=float, help="最小主力净流入占比 (%%)")
    parser.add_argument("--main-net-ratio-max", type=float, help="最大主力净流入占比 (%%)")
    parser.add_argument("--rsi-min", type=float, help="最小RSI")
    parser.add_argument("--rsi-max", type=float, help="最大RSI")
    parser.add_argument("--exclude-downtrend", action="store_true",
                       help="排除下跌趋势股票（MA5<MA20 或近20日涨幅<-10%）")
    parser.add_argument("--include-banned-board", action="store_true",
                       help="包含科创板/创业板（默认排除）")
    parser.add_argument("--weights", type=str, help="评分权重JSON字符串，格式: {\"pe\":15,\"pb\":10,...}")

    args = parser.parse_args()

    # 构建筛选条件
    filter_keys = [
        'pe_max', 'pe_min', 'pb_max', 'pb_min', 'roe_min',
        'debt_ratio_max', 'dividend_min', 'market_cap_min', 'market_cap_max',
        'volume_ratio_min', 'volume_ratio_max',
        'main_net_ratio_min', 'main_net_ratio_max',
        'rsi_min', 'rsi_max',
        'exclude_downtrend'
    ]
    filters = {
        k: getattr(args, k.replace('-', '_'))
        for k in filter_keys
        if getattr(args, k.replace('-', '_')) is not None
    }

    # 科创板/创业板过滤（默认排除）
    filters['exclude_banned_board'] = not args.include_banned_board

    # 评分权重
    score_weights = None
    if args.weights:
        try:
            score_weights = json.loads(args.weights)
        except json.JSONDecodeError:
            print("警告: 权重JSON格式错误，将使用默认权重")
            score_weights = None

    # 执行筛选
    screener = StockScreener()
    results = screener.screen(
        scope=args.scope,
        filters=filters if filters else None,
        sort_by=args.sort_by,
        top_n=args.top,
        score_weights=score_weights
    )

    # 输出结果
    output = {
        "screen_time": datetime.now().isoformat(),
        "scope": args.scope,
        "filters": filters,
        "count": len(results),
        "results": results
    }

    output_json = json.dumps(output, ensure_ascii=False, indent=2, default=str)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        print(f"筛选结果已保存到: {args.output}")
        print(f"共筛选出 {len(results)} 只股票")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
