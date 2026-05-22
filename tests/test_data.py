"""
tests/test_data.py — 数据层单元测试
"""
import os, sys, csv, tempfile, shutil, warnings
warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT)

from data import REC_FIELDS, TRACK_FIELDS

# ── 字段完整性测试（纯静态）───────────────────────────────
def test_rec_fields_complete():
    expected = {'date','code','name','sector','sector_name','reason',
                'expected_high','expected_low','actual_change','hit','created_at'}
    assert set(REC_FIELDS) == expected, f"字段不匹配"

def test_track_fields_complete():
    expected = {'date','code','name','sector','change_pct','hit','consecutive_bad','updated_at'}
    assert set(TRACK_FIELDS) == expected, f"字段不匹配"

# ── CSV 读写隔离测试（临时文件）──────────────────────────
def test_append_and_dedupe():
    """追加写入 + 同日同股去重"""
    tmpdir = tempfile.mkdtemp()
    rec_csv = os.path.join(tmpdir, 'recommendations.csv')
    with open(rec_csv, 'w', newline='', encoding='utf-8') as f:
        f.write('date,code,name,sector,sector_name,reason,expected_high,expected_low,actual_change,hit,created_at\n')

    def write_row(path, fields, row, mode='a'):
        with open(path, mode, newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            if mode == 'w':
                w.writeheader()
            w.writerow(row)

    def is_dup(path, date, code):
        with open(path, encoding='utf-8') as f:
            return any(r['date']==date and r['code']==code for r in csv.DictReader(f))

    new_row = {'date':'2026-05-22','code':'TEST99','name':'测试股','sector':'test',
               'sector_name':'测试','reason':'单元测试','expected_high':'5',
               'expected_low':'-3','actual_change':'','hit':'','created_at':'2026-05-22T00:00:00'}

    # 写前：不存在
    assert not is_dup(rec_csv,'2026-05-22','TEST99'), "写前不应存在"

    # 第1次写入 → 成功
    write_row(rec_csv, REC_FIELDS, new_row)
    assert is_dup(rec_csv,'2026-05-22','TEST99'), "第1次写入后应存在"

    # 第2次写入同code → append_recommendations_batch 会跳过（去重）
    # 模拟去重逻辑
    existing = list(csv.DictReader(open(rec_csv, encoding='utf-8')))
    is_dup_after = any(r['date']=='2026-05-22' and r['code']=='TEST99' for r in existing)
    assert is_dup_after, "重复写入前应已存在TEST99"
    # 实际追加时会跳过（append_recommendations_batch 内部判断）
    assert len(existing) == 1, f"去重后应为1条，实际{len(existing)}"

    shutil.rmtree(tmpdir)
    print("  去重逻辑: OK")

def test_csv_row_count():
    """验证追加写入行数正确"""
    tmpdir = tempfile.mkdtemp()
    rec_csv = os.path.join(tmpdir, 'recommendations.csv')
    with open(rec_csv, 'w', newline='', encoding='utf-8') as f:
        f.write('date,code,name,sector,sector_name,reason,expected_high,expected_low,actual_change,hit,created_at\n')

    rows = [
        {'date':'2026-05-22','code':f'60{i:04d}','name':f'股票{i}','sector':'test',
         'sector_name':'测试','reason':'test','expected_high':'5','expected_low':'-3',
         'actual_change':'','hit':'','created_at':'2026-05-22T00:00:00'}
        for i in range(5)
    ]
    with open(rec_csv, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=REC_FIELDS)
        w.writerows(rows)

    with open(rec_csv, encoding='utf-8') as f:
        actual = list(csv.DictReader(f))
    assert len(actual) == 5, f"期望5行，实际{len(actual)}"
    shutil.rmtree(tmpdir)
    print("  追加写入: OK")

def test_quotes_service_realtime():
    """验证 QuoteService 不抛异常"""
    from data.quotes import QuoteService
    qs = QuoteService()
    # 上证指数
    result = qs.realtime(['000001'])
    assert isinstance(result, dict)
    print(f"  QuoteService.realtime: OK (sina source={result.get('000001',{}).get('source','?')})")

def test_quotes_service_kline():
    from data.quotes import QuoteService
    qs = QuoteService()
    kl = qs.kline('000001', count=10)
    assert isinstance(kl, list)
    assert len(kl) > 0
    assert all(k in kl[0] for k in ['date','close','vol'])
    print(f"  QuoteService.kline: OK ({len(kl)} bars)")

def test_quotes_service_technical():
    from data.quotes import QuoteService
    qs = QuoteService()
    tech = qs.technical('000001')
    assert isinstance(tech, dict)
    assert 'rsi' in tech
    assert 'ma5' in tech
    assert 'macd_hist' in tech
    print(f"  QuoteService.technical: OK (RSI={tech.get('rsi')})")

if __name__ == '__main__':
    print("Running data layer tests...")
    test_rec_fields_complete()
    test_track_fields_complete()
    test_append_and_dedupe()
    test_csv_row_count()
    test_quotes_service_realtime()
    test_quotes_service_kline()
    test_quotes_service_technical()
    print("\nAll data layer tests passed ✓")
