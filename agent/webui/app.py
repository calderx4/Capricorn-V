"""
Capricorn WebUI - Streamlit 前端

通过 Gateway API 与 agent 对话，侧边栏管理 Cron 任务和通知。
启动方式：python run.py --mode gateway_with_webui
"""

import requests
import streamlit as st

# ── 配置 ────────────────────────────────────────────

API_BASE = st.secrets.get("api_base", "http://127.0.0.1:8080")

# ── 页面配置 ────────────────────────────────────────

st.set_page_config(
    page_title="Capricorn",
    page_icon="🤖",
    layout="wide",
)

if "messages" not in st.session_state:
    st.session_state.messages = []

if "unread_count" not in st.session_state:
    st.session_state.unread_count = 0

st.title("🤖 Capricorn")

# ── 侧边栏 ─────────────────────────────────────────

with st.sidebar:
    # ── Cron 任务 ──────────────────────────────────
    st.header("⏰ Cron 任务")

    try:
        resp = requests.get(f"{API_BASE}/jobs", timeout=5)
        jobs = resp.json().get("jobs", [])
    except Exception:
        jobs = []

    if jobs:
        for job in jobs:
            status_icon = {"active": "🟢", "paused": "⏸️", "queued": "⏳", "running": "🔄"}.get(job.get("status"), "⚪")
            type_label = "🔄" if job.get("type") == "recurring" else "📌"
            with st.expander(f"{status_icon} {type_label} {job.get('name', 'unnamed')}"):
                st.caption(f"ID: `{job['id']}`")
                job_type = job.get("type", "once")
                st.text(f"类型: {'重复' if job_type == 'recurring' else '一次性'}")
                st.text(f"调度: {job.get('schedule', '-')}")
                if job.get("repeat") is not None:
                    st.text(f"剩余次数: {job['repeat']}")
                if job.get("end_at"):
                    st.text(f"截止: {job['end_at'][:16]}")
                run_status = job.get("last_run_status") or "-"
                run_status_icon = "✅" if run_status == "success" else ("❌" if run_status == "failed" else "⚪")
                st.text(f"上次执行: {run_status_icon} {run_status}")
                st.text(f"下次执行: {job.get('next_run_at', '-')[:19]}")
                if st.button("删除", key=f"del_{job['id']}"):
                    try:
                        resp = requests.post(
                            f"{API_BASE}/chat",
                            json={"prompt": f"删除定时任务 {job['id']}"},
                            timeout=60,
                        )
                        st.success("已删除")
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除失败: {e}")
    else:
        st.info("暂无定时任务")

    st.divider()

    # ── 通知 ───────────────────────────────────────
    st.header("🔔 通知")

    try:
        resp = requests.get(f"{API_BASE}/notifications?unread=true&limit=10", timeout=5)
        notifications = resp.json().get("notifications", [])
    except Exception:
        notifications = []

    st.session_state.unread_count = len(notifications)

    if notifications:
        st.warning(f"{len(notifications)} 条未读")
        for n in reversed(notifications):
            d = n["data"]
            status_icon = "✅" if d.get("status") == "success" else "❌"
            ts = n["timestamp"][:16]
            with st.expander(f"{status_icon} {d.get('job_name', '未命名')} ({ts})"):
                st.caption(f"ID: `{n['id']}`")
                st.text(d.get("message", "")[:500])
                if st.button("标记已读", key=f"read_{n['id']}"):
                    try:
                        requests.post(
                            f"{API_BASE}/notifications/read",
                            json={"ids": [n["id"]]},
                            timeout=5,
                        )
                        st.rerun()
                    except Exception:
                        pass
    else:
        st.info("暂无未读通知")

    st.divider()
    st.caption(f"Gateway: `{API_BASE}`")

# ── 聊天界面 ────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("输入消息..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            try:
                resp = requests.post(
                    f"{API_BASE}/chat",
                    json={"prompt": prompt},
                    timeout=500,
                )
                data = resp.json()
                if data.get("error"):
                    response = f"**错误:** {data['error']}"
                else:
                    response = data.get("response", "（无响应）")
            except requests.exceptions.ConnectionError:
                response = "**连接失败:** Gateway 未启动"
            except Exception as e:
                response = f"**错误:** {e}"

        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})

# ── SSE 实时通知轮询 ───────────────────────────────
# 用 st.fragment 实现定时刷新通知（Streamlit 1.37+）
try:
    @st.fragment(run_every="10s")
    def _poll_notifications():
        try:
            resp = requests.get(f"{API_BASE}/notifications?unread=true&limit=10", timeout=5)
            new_count = len(resp.json().get("notifications", []))
            if new_count > st.session_state.unread_count:
                st.toast(f"📬 收到 {new_count - st.session_state.unread_count} 条新通知")
                st.session_state.unread_count = new_count
                st.rerun()
            st.session_state.unread_count = new_count
        except Exception:
            pass

    _poll_notifications()
except Exception:
    pass
