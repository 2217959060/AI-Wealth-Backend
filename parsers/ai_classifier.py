from dotenv import load_dotenv
load_dotenv()
import os
import json
import time
from openai import OpenAI

# 初始化大模型客户端
client = OpenAI(
    api_key=os.getenv("ZHIPUAI_API_KEY"),
    base_url="https://open.bigmodel.cn/api/paas/v4/"
)

# 系统内置的标准分类库
STANDARD_CATEGORIES = ["餐饮", "交通", "购物", "居住", "娱乐", "医疗", "工资", "理财", "其他"]


def classify_batch_bills(bills_batch):
    """
    给大模型发送一个批次的账单（例如50条），让其返回对应的分类列表
    bills_batch 格式: [{"id": 0, "desc": "对方:小电科技 | 说明:小电科技充电宝"}, ...]
    """
    prompt = f"""
    你是一个极其精准的财务账单分类引擎。
    请分析以下交易描述，并严格将其归入以下标准分类之一：{STANDARD_CATEGORIES}。
    如果没有合适的，请务必归为"其他"。

    待分类的账单批次数据：
    {json.dumps(bills_batch, ensure_ascii=False)}

    【绝对规则】
    必须且只能返回纯 JSON 格式数据！严禁包含任何 markdown 符号、解释性文字。
    JSON 格式必须为：
    {{
        "results": [
            {{"id": 0, "category": "交通"}},
            {{"id": 1, "category": "餐饮"}}
        ]
    }}
    """

    try:
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        # 解析大模型返回的 JSON
        res_json = json.loads(response.choices[0].message.content)
        return res_json.get("results", [])

    except Exception as e:
        print(f"⚠️ 批次处理失败: {e}")
        return []


def run_ai_classification(standardized_bills, batch_size=50):
    """
    主控函数：将成百上千条账单切片，排队送入 AI 处理
    """
    print(f"🤖 启动 AI 智能分类引擎，待处理数据：{len(standardized_bills)} 条...")

    # 1. 组装精简版数据喂给 AI（为了省 Token，我们不传金额和日期，只传描述）
    ai_tasks = []
    for i, bill in enumerate(standardized_bills):
        ai_tasks.append({"id": i, "desc": bill["raw_desc"]})

    final_results = []

    # 2. 对列表进行批次切割
    total_batches = (len(ai_tasks) + batch_size - 1) // batch_size

    for i in range(total_batches):
        batch = ai_tasks[i * batch_size: (i + 1) * batch_size]
        print(f"⏳ 正在处理第 {i + 1}/{total_batches} 批次 ({len(batch)}条)...")

        # 调用大模型
        batch_results = classify_batch_bills(batch)
        final_results.extend(batch_results)

        # 频率控制：防止触发 API 的每秒并发限制 (Rate Limit)
        time.sleep(1)

        # 3. 将大模型预测的 category 缝合回原始数据中
    # 建立一个基于 id 的快速查找字典
    category_map = {item["id"]: item.get("category", "其他") for item in final_results}

    for i, bill in enumerate(standardized_bills):
        bill["category"] = category_map.get(i, "其他")

    print("✅ AI 智能分类全部完成！")
    return standardized_bills


# ================= 单元测试入口 =================
if __name__ == "__main__":
    from bill_extractor import UniversalBillParser

    # 1. 先用我们上一步的引擎解析文件
    test_file = r"../data/bill_test_data/微信支付交易明细证明(20260101-20260609)_20260609221759.pdf"
    parser = UniversalBillParser(test_file)
    raw_bills = parser.parse()

    # 为了测试快速出结果，我们只截取前 10 条账单喂给 AI
    test_bills = raw_bills[:10]

    # 2. 扔给 AI 智能打标
    classified_bills = run_ai_classification(test_bills, batch_size=10)

    print("\n🎉 最终成果预览：")
    for b in classified_bills:
        print(f"[{b['category']}] | {b['date']} | ¥{b['amount']} | {b['raw_desc']}")