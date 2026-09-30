from pathlib import Path
from datetime import datetime, timezone, timedelta
from io import BytesIO
import csv
import hashlib
import hmac
import secrets
import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(page_title="미용학과 우리 반 설문", page_icon="📝", layout="centered")
BASE = Path(__file__).resolve().parent
DB = BASE / "class_responses.sqlite3"
PASSWORD_FILE = BASE / "teacher_password.txt"

# 최초 실행 때만 교사용 비밀번호를 생성합니다. 학생 화면에는 표시하지 않습니다.
try:
    with PASSWORD_FILE.open("x", encoding="utf-8") as f:
        f.write(secrets.token_urlsafe(18))
except FileExistsError:
    pass
ADMIN_PASSWORD = PASSWORD_FILE.read_text(encoding="utf-8").strip()

FIELDS = ["제출시간", "학년", "반", "번호", "이름", "성별", "좋아하는색", "좋아하는음악", "희망여행지", "MBTI", "희망직업군", "배우고싶은실습", "수업지원희망", "퍼스널컬러"]
COLORS = ["빨강·분홍 계열", "주황·노랑 계열", "초록 계열", "파랑 계열", "보라 계열", "무채색 — 검정·하양·회색"]
MUSIC = ["K-POP·아이돌 음악", "발라드·OST", "힙합·R&B", "록·인디", "재즈·클래식", "전자음악·EDM"]
TRAVEL = ["바다·해변", "산·숲·자연", "대도시·쇼핑", "역사·문화유적", "테마파크·놀이공원", "휴양지·리조트"]
JOBS = ["헤어 분야 — 디자이너·컬러리스트", "메이크업·분장 분야 — 메이크업 아티스트·특수분장사", "네일 분야 — 네일 아티스트", "피부·스파 분야 — 피부미용사·스파 테라피스트", "화장품 분야 — 제품 기획·연구·마케팅", "뷰티 콘텐츠 분야 — 크리에이터·뷰티 에디터", "이미지 컨설팅 분야 — 퍼스널 컬러·이미지 컨설턴트", "뷰티 교육·경영 분야 — 미용 강사·매장 운영"]
MBTI = ["ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP", "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ", "모름"]


def connect():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = connect()
    try:
        defs = ', '.join('"' + c + '" TEXT NOT NULL' for c in FIELDS)
        conn.execute('CREATE TABLE IF NOT EXISTS responses (id INTEGER PRIMARY KEY AUTOINCREMENT, ' + defs + ', UNIQUE("학년", "반", "번호"))')
        conn.commit()
    finally:
        conn.close()


def save_response(row):
    conn = connect()
    try:
        cols = ', '.join('"' + c + '"' for c in FIELDS)
        placeholders = ', '.join('?' for _ in FIELDS)
        conn.execute('INSERT INTO responses (' + cols + ') VALUES (' + placeholders + ')', [str(row[c]) for c in FIELDS])
        conn.commit()
    finally:
        conn.close()


def read_responses():
    conn = connect()
    try:
        return pd.read_sql_query('SELECT * FROM responses ORDER BY CAST("학년" AS INTEGER), CAST("반" AS INTEGER), CAST("번호" AS INTEGER)', conn)
    finally:
        conn.close()


def delete_response(response_id):
    conn = connect()
    try:
        conn.execute('DELETE FROM responses WHERE id = ?', (int(response_id),))
        conn.commit()
    finally:
        conn.close()


def safe_cell(value):
    # CSV/Excel로 열 때 사용자 입력이 수식으로 해석되지 않도록 처리합니다.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def optional_choice(label, choices, key):
    return st.selectbox(label, choices, index=None, placeholder="선택하세요. 응답하지 않아도 됩니다.", key=key)


init_db()
st.title("미용학과 우리 반 알아보기")
st.caption("우리의 취향과 진로를 함께 알아보는 학급 설문입니다.")
st.info("처음에는 가상 이름으로 시험해 주세요. 실제 학생 정보를 수집하기 전에는 선생님이 학교의 개인정보 처리 절차, 안내문, 보관·삭제 일정을 확인해야 합니다.")

with st.sidebar:
    st.header("화면 선택")
    mode = st.radio("이용할 화면을 선택하세요.", ["학생 설문", "교사 관리"])
    st.caption("응답은 앱이 실행되는 컴퓨터에 저장됩니다. Google 스프레드시트 자동 연동은 포함되어 있지 않습니다.")

if mode == "학생 설문":
    st.write("학년·반·번호·이름과 안내 확인은 필수입니다. 나머지 질문은 자유롭게 건너뛰어도 됩니다.")
    with st.expander("개인정보 및 설문 이용 안내", expanded=True):
        st.write("학급 활동과 진로 지도를 위한 설문입니다. 응답에는 이름과 학급 정보가 포함되며, 교사 관리 화면에서 확인할 수 있습니다. 학생 화면에는 다른 학생의 응답이 표시되지 않습니다.")
        st.write("실제 운영 시 담당 교사가 수집 근거, 보관 기간, 삭제 일정, 정정·삭제 문의 방법을 별도로 안내해야 합니다. 시험 단계에서는 실제 개인정보를 입력하지 마세요.")
    with st.form("class_survey"):
        st.subheader("기본 정보")
        c1, c2, c3 = st.columns(3)
        with c1:
            grade = st.selectbox("학년 *", [1, 2, 3], index=None, placeholder="선택하세요.")
        with c2:
            class_no = st.number_input("반 *", min_value=1, max_value=99, value=None, step=1, placeholder="숫자로 입력하세요.")
        with c3:
            number = st.number_input("번호 *", min_value=1, max_value=99, value=None, step=1, placeholder="숫자로 입력하세요.")
        name = st.text_input("이름 *", max_chars=30, placeholder="시험할 때는 가상 이름을 입력하세요.")
        gender = optional_choice("성별", ["여성", "남성", "기타", "응답하지 않음"], "gender")
        st.subheader("나의 취향과 성향")
        color = optional_choice("가장 좋아하는 색 계열", COLORS, "color")
        music = optional_choice("가장 좋아하는 음악 장르", MUSIC, "music")
        travel = optional_choice("가장 가고 싶은 여행지 유형", TRAVEL, "travel")
        mbti = optional_choice("나의 MBTI", MBTI, "mbti")
        st.caption("MBTI는 자기소개를 위한 참고 항목이며, 능력이나 진로를 판단하는 기준으로 사용하지 않습니다.")
        st.subheader("미용학과 전공과 진로")
        job = optional_choice("현재 가장 관심 있는 희망 직업군", JOBS, "job")
        st.caption("아직 결정하지 않았거나 다른 분야를 희망하면 선택하지 않아도 됩니다.")
        practice = optional_choice("가장 배우고 싶은 실습", ["커트·스타일링", "염색·펌", "메이크업", "네일아트", "피부 관리", "퍼스널 컬러·이미지 연출"], "practice")
        support = optional_choice("수업에서 가장 도움받고 싶은 부분", ["기초 이론 이해", "실습 기술 향상", "자격증 준비", "포트폴리오 제작", "진로·취업 탐색", "고객 응대·상담"], "support")
        personal = optional_choice("내가 알고 있는 퍼스널 컬러", ["봄 웜톤", "여름 쿨톤", "가을 웜톤", "겨울 쿨톤", "모름"], "personal")
        notice = st.checkbox("설문의 목적과 개인정보 안내를 확인했습니다. *")
        submitted = st.form_submit_button("설문 제출하기", type="primary", use_container_width=True)
    if submitted:
        if grade is None or class_no is None or number is None or not name.strip():
            st.error("학년, 반, 번호, 이름을 모두 입력해 주세요.")
        elif not notice:
            st.error("개인정보 안내를 읽고 확인란을 체크해 주세요.")
        else:
            now = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")
            values = [now, grade, class_no, number, name.strip(), gender, color, music, travel, mbti, job, practice, support, personal]
            row = dict(zip(FIELDS, ["미응답" if v is None else v for v in values]))
            try:
                save_response(row)
            except sqlite3.IntegrityError:
                st.warning("같은 학년·반·번호로 이미 제출한 응답이 있습니다. 수정하려면 선생님께 문의해 주세요.")
            except sqlite3.Error:
                st.error("저장하지 못했습니다. 잠시 후 다시 시도하거나 선생님께 알려 주세요.")
            else:
                st.success("설문 응답을 저장했습니다. 감사합니다!")
                st.caption("응답 내용 변경은 선생님께 문의해 주세요. 이 설문은 학번의 실제 소유자를 인증하지는 않습니다.")
else:
    st.subheader("교사 관리")
    st.caption("최초 실행 시 앱 파일과 같은 폴더에 생성되는 teacher_password.txt에서 비밀번호를 확인하세요. 파일을 학생에게 공유하지 마세요.")
    if not st.session_state.get("teacher_authenticated", False):
        with st.form("teacher_login"):
            password = st.text_input("교사 비밀번호", type="password")
            login = st.form_submit_button("로그인")
        if login:
            supplied = hashlib.sha256(password.encode("utf-8")).digest()
            expected = hashlib.sha256(ADMIN_PASSWORD.encode("utf-8")).digest()
            if ADMIN_PASSWORD and hmac.compare_digest(supplied, expected):
                st.session_state.teacher_authenticated = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
        st.stop()
    if st.button("교사 로그아웃"):
        st.session_state.teacher_authenticated = False
        st.rerun()
    st.warning("사용을 마치면 로그아웃하세요. 내려받은 파일에도 학생 개인정보가 들어 있습니다.")
    df = read_responses()
    st.write(f"현재 저장된 응답은 {len(df)}건입니다.")
    if st.button("응답 새로고침"):
        st.rerun()
    if df.empty:
        st.info("아직 제출된 응답이 없습니다. 학생 설문에서 가상 이름으로 먼저 시험해 주세요.")
    else:
        st.dataframe(df.drop(columns=["id"]), hide_index=True, use_container_width=True)
        export = df.drop(columns=["id"]).copy()
        for col in export.columns:
            export[col] = export[col].map(safe_cell)
        for col in ["학년", "반", "번호"]:
            export[col] = pd.to_numeric(export[col])
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            export.to_excel(writer, sheet_name="설문응답", index=False)
            ws = writer.sheets["설문응답"]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for column in ws.columns:
                ws.column_dimensions[column[0].column_letter].width = 22
        stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
        st.download_button("엑셀 파일 내려받기 (.xlsx)", buffer.getvalue(), file_name=f"우리반_설문응답_{stamp}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("CSV 파일 내려받기", export.to_csv(index=False, quoting=csv.QUOTE_ALL).encode("utf-8-sig"), file_name=f"우리반_설문응답_{stamp}.csv", mime="text/csv")
        with st.expander("시험 응답 삭제 / 잘못 제출한 응답 삭제"):
            st.write("삭제한 응답은 복구할 수 없습니다. 응답을 수정해야 한다면 해당 응답을 삭제한 뒤 학생이 다시 제출하도록 안내하세요.")
            labels = {int(r["id"]): f'{r["학년"]}학년 {r["반"]}반 {r["번호"]}번 · {r["이름"]}' for _, r in df.iterrows()}
            with st.form("delete_one"):
                chosen = st.selectbox("삭제할 응답", list(labels), format_func=lambda x: labels[x], index=None, placeholder="응답을 선택하세요.")
                confirmed = st.checkbox("선택한 응답을 영구 삭제하는 것을 확인했습니다.")
                delete = st.form_submit_button("선택한 응답 삭제")
            if delete:
                if chosen is None or not confirmed:
                    st.error("삭제할 응답을 선택하고 확인란을 체크하세요.")
                else:
                    delete_response(chosen)
                    st.rerun()
