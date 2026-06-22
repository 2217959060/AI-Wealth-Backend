import os
import pandas as pd
import pdfplumber
import re


class UniversalBillParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_ext = os.path.splitext(file_path)[1].lower()
        self.filename = os.path.basename(file_path)

    def parse(self):
        """核心分发器：自动嗅探文件格式并移交对应解析器"""
        print(f"🔍 正在嗅探文件: {self.filename}...")

        if self.file_ext == '.csv':
            return self._parse_csv()
        elif self.file_ext == '.pdf':
            return self._parse_pdf()
        else:
            raise ValueError(f"❌ 不支持的文件格式: {self.file_ext}")

    def _find_csv_header(self, encoding='utf-8'):
        """🧠 避坑神技：动态寻找真实表头，无视开头的废话"""
        with open(self.file_path, 'r', encoding=encoding, errors='ignore') as f:
            for i, line in enumerate(f):
                # 只要这行同时包含这些关键字，断定它就是真实表头！
                if "交易时间" in line and ("金额" in line or "金额(元)" in line):
                    return i
        return 0  # 没找到就默认第一行

    def _parse_csv(self):
        """解析 CSV 账单 (兼容微信 & 支付宝)"""
        # 💣 坑点防范：国内大厂导出的 CSV 编码极其混乱，通常是 utf-8-sig 或 gbk
        encodings_to_try = ['utf-8-sig', 'gbk', 'utf-8']
        df = None

        for enc in encodings_to_try:
            try:
                # 动态找到真正表头所在的行号
                header_row_index = self._find_csv_header(encoding=enc)
                df = pd.read_csv(self.file_path, encoding=enc, skiprows=header_row_index)
                break  # 读取成功就跳出循环
            except Exception as e:
                continue

        if df is None:
            raise Exception("❌ CSV 编码解析彻底失败，请检查文件！")

        # 🧹 清洗列名（去掉空格等脏字符）
        df.columns = [col.strip() for col in df.columns]

        standard_data = []

        # 💡 判别是微信还是支付宝
        if "交易类型" in df.columns and "当前状态" in df.columns:
            print("🟢 识别为：微信 CSV 账单")
            # 过滤掉微信特有的废数据：中性交易、退款
            df = df[~df['收/支'].astype(str).str.contains('中性交易|/', na=False)]

            for _, row in df.iterrows():
                try:
                    # 去掉金额里的特殊符号，比如 "¥15.00" -> "15.00"
                    amt_str = str(row['金额(元)']).replace('¥', '').replace(',', '').strip()
                    amount = float(amt_str)

                    standard_data.append({
                        "date": str(row['交易时间']).strip(),
                        "amount": amount,
                        "type": "expense" if "支" in str(row['收/支']) else "income",
                        "raw_desc": f"对方:{row['交易对方']} | 商品:{row['商品']}"
                    })
                except Exception:
                    continue  # 遇到脏数据行直接跳过，保证程序不崩

        elif "交易分类" in df.columns and "交易状态" in df.columns:
            print("🔵 识别为：支付宝 CSV 账单")
            # 过滤掉支付宝特有的废数据：不计收支、退款
            df = df[~df['收/支'].astype(str).str.contains('不计收支|/', na=False)]

            for _, row in df.iterrows():
                try:
                    amount = float(str(row['金额']).replace(',', '').strip())
                    standard_data.append({
                        "date": str(row['交易时间']).strip(),
                        "amount": amount,
                        "type": "expense" if "支" in str(row['收/支']) else "income",
                        "raw_desc": f"对方:{row['交易对方']} | 说明:{row['商品说明']}"
                    })
                except Exception:
                    continue

        return standard_data

    def _parse_pdf(self):
        """解析 PDF 账单 (高级物理表格抽取)"""
        standard_data = []
        try:
            with pdfplumber.open(self.file_path) as pdf:
                first_page_text = pdf.pages[0].extract_text()
                is_wechat = "微信支付交易明细证明" in first_page_text
                is_alipay = "支付宝" in first_page_text

                for page in pdf.pages:
                    # 使用默认的网格策略提取表格
                    table = page.extract_table()
                    if not table:
                        continue

                    for row in table:
                        # 过滤空行或表头
                        if not row or "交易时间" in str(row) or "金额" in str(row):
                            continue

                        # 🧹 清洗：把单元格里折叠换行的文本强行拼成一行
                        row = [str(cell).replace('\n', '').strip() if cell else '' for cell in row]

                        try:
                            if is_wechat and len(row) >= 8:
                                # 微信PDF列序: 时间(0), 单号(1), 类型(2), 收/支/其他(3), 方式(4), 金额(5), 商户单号(6), 对方(7)
                                if "中性交易" in row[3] or "其他" in row[3]:
                                    continue
                                # 提取纯数字
                                amount = float(re.sub(r'[^\d.]', '', row[5]))
                                standard_data.append({
                                    "date": row[0][:19],
                                    "amount": amount,
                                    "type": "expense" if "支" in row[3] else "income",
                                    "raw_desc": f"对方:{row[7]} | 类型:{row[2]}"
                                })

                            elif is_alipay and len(row) >= 8:
                                # 支付宝PDF列序: 收/支(0), 对方(1), 说明(2), 方式(3), 金额(4), 单号(5), 单号(6), 时间(7)
                                if "不计收支" in row[0]:
                                    continue
                                amount = float(re.sub(r'[^\d.]', '', row[4]))
                                standard_data.append({
                                    "date": row[7][:19],
                                    "amount": amount,
                                    "type": "expense" if "支" in row[0] else "income",
                                    "raw_desc": f"对方:{row[1]} | 说明:{row[2]}"
                                })
                        except Exception as e:
                            # 遇到跨页断裂的残缺行，直接跳过
                            continue

        except Exception as e:
            print(f"❌ PDF 解析失败: {e}")

        return standard_data

# ================= 单元测试入口 =================
if __name__ == "__main__":
    # ⚠️ 请把这里换成你本地 bill_test_data 文件夹里的某个 CSV 文件名！
    # 比如: test_file = "../bill_test_data/支付宝交易明细(20260101-20260609).csv"
    test_file = r"../data/bill_test_data/微信支付交易明细证明(20260101-20260609)_20260609221759.pdf"

    try:
        parser = UniversalBillParser(test_file)
        result = parser.parse()

        print(f"\n✅ 成功解析出 {len(result)} 条标准账单！")
        print("前 3 条数据预览：")
        for item in result[:3]:
            print(item)
    except Exception as e:
        print(f"调试报错: {e}")