from datetime import datetime, timezone, timedelta
from io import BytesIO
from urllib.parse import urlparse
import csv
import hashlib
import hmac
import time
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="미용학과 우리 반 설문", page_icon="📝", layout="centered")

# 비밀정보는 Streamlit Secrets에만 입력합니다.
try:
    WEB_APP_URL = str(st.secrets["APPS_SCRIPT_URL"]).strip()
    WRITE_SECRET = str(st.secrets["WRITE_SECRET"])
    ADMIN_SECRET = str(st.secrets["ADMIN_SECRET"])
    ADMIN_PASSWORD = str(st.secrets["TEACHER_PASSWORD"])
    CLASS_CODE = str(st.secrets["CLASS_CODE"])
    DEMO_MODE = st.secrets.get("DEMO_MODE", True)
    u = urlparse(WEB_APP_URL)
    if (u.scheme != "https" or u.netloc != "script.google.com"
            or not u.path.startswith("/macros/s/") or not u.path.endswith("/exec")
            or u.query or u.fragment):
        raise ValueError("URL")
    if (min(len(WRITE_SECRET), len(ADMIN_SECRET)) < 40
            or WRITE_SECRET == ADMIN_SECRET
            or len(ADMIN_PASSWORD) < 12 or len(CLASS_CODE) < 8
            or ADMIN_PASSWORD == CLASS_CODE or not isinstance(DEMO_MODE, bool)):
        raise ValueError("configuration")
    if any("여기에" in x for x in [WEB_APP_URL, WRITE_SECRET, ADMIN_SECRET, ADMIN_PASSWORD, CLASS_CODE]):
        raise ValueError("placeholder")
except Exception:
    st.error("연결 설정이 준비되지 않았습니다. 선생님이 Streamlit Secrets 설정을 확인해 주세요.")
    st.stop()

FIELDS = ["제출시간", "학년", "반", "번호", "이름", "성별", "좋아하는색", "좋아하는음악", "희망여행지", "MBTI", "희망직업군", "배우고싶은실습", "수업지원희망", "퍼스널컬러"]
COLORS = ["빨강·분홍 계열", "주황·노랑 계열", "초록 계열", "파랑 계열", "보라 계열", "무채색 — 검정·하양·회색"]
MUSIC = ["K-POP·아이돌 음악", "발라드·OST", "힙합·R&B", "록·인디", "재즈·클래식", "전자음악·EDM"]
TRAVEL = ["바다·해변", "산·숲·자연", "대도시·쇼핑", "역사·문화유적", "테마파크·놀이공원", "휴양지·리조트"]
JOBS = ["헤어 분야 — 디자이너·컬러리스트", "메이크업·분장 분야 — 메이크업 아티스트·특수분장사", "네일 분야 — 네일 아티스트", "피부·스파 분야 — 피부미용사·스파 테라피스트", "화장품 분야 — 제품 기획·연구·마케팅", "뷰티 콘텐츠 분야 — 크리에이터·뷰티 에디터", "이미지 컨설팅 분야 — 퍼스널 컬러·이미지 컨설턴트", "뷰티 교육·경영 분야 — 미용 강사·매장 운영"]
MBTI = ["ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP", "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ", "모름"]


class BridgeError(Exception):
    pass


class DuplicateResponse(BridgeError):
    pass


def bridge_request(action, **params):
    secret = WRITE_SECRET if action == "submit" else ADMIN_SECRET
    try:
        # 비밀값은 URL이나 로그가 아니라 HTTPS 요청 본문으로만 전달합니다.
        response = requests.post(
            WEB_APP_URL, json={"action": action, "secret": secret, **params},
            timeout=(10, 40), allow_redirects=True,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError):
        raise BridgeError("서버 응답을 확인하지 못했습니다. 제출·삭제 요청은 이미 처리되었을 수도 있으니 교사가 시트에서 확인한 뒤 다시 시도해 주세요.") from None
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        raise BridgeError("연결 프로그램 응답 형식이 맞지 않습니다. 배포 URL과 버전을 확인해 주세요.")
    if not result["ok"]:
        code = result.get("code", "SERVER_ERROR")
        if code == "DUPLICATE":
            raise DuplicateResponse("같은 학년·반·번호의 응답이 이미 있습니다.")
        messages = {
            "AUTH": "연결 인증에 실패했습니다. 선생님이 양쪽 비밀값 설정을 확인해 주세요.",
            "CONFIG": "Apps Script의 초기 설정이 필요합니다.",
            "SCHEMA": "설문응답 시트의 제목 행이 앱 설정과 다릅니다. 시트를 임의로 수정하지 말고 확인해 주세요.",
            "INVALID": "입력값 형식이 올바르지 않습니다.",
            "BUSY": "다른 응답을 처리 중입니다. 잠시 후 다시 시도해 주세요.",
            "LIMIT": "이 앱의 응답 보관 한도에 도달했습니다. 선생님께 알려 주세요.",
            "SERVER_ERROR": "Google 연결 또는 시트 처리 중 오류가 발생했습니다. 처리 여부를 시트에서 확인해 주세요.",
        }
        raise BridgeError(messages.get(code, "연결 프로그램에서 요청을 처리하지 못했습니다."))
    return result


def save_response(row):
    bridge_request("submit", row=row)


def read_responses():
    result = bridge_request("list")
    rows = result.get("rows")
    columns = ["id"] + FIELDS
    if not isinstance(rows, list) or len(rows) > 5000 or any(
            not isinstance(r, dict) or set(r) != set(columns) for r in rows):
        raise BridgeError("응답 목록 형식이 맞지 않습니다.")
    df = pd.DataFrame(rows, columns=columns)
    if not df.empty:
        df = df.sort_values(["학년", "반", "번호"], key=lambda x: pd.to_numeric(x, errors="coerce"))
    return df


def delete_response(response_id):
    bridge_request("delete", id=str(response_id))


def same_secret(supplied, expected):
    return hmac.compare_digest(
        hashlib.sha256(supplied.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def safe_cell(value):
    # CSV/Excel로 열 때 사용자 입력이 수식으로 해석되지 않도록 처리합니다.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def optional_choice(label, choices, key):
    return st.selectbox(label, choices, index=None, placeholder="선택하세요. 응답하지 않아도 됩니다.", key=key)


st.title("미용학과 우리 반 알아보기")
st.caption("우리의 취향과 진로를 함께 알아보는 학급 설문입니다.")
if DEMO_MODE:
    st.warning("현재 시험 운영 중입니다. 실제 학생 정보 대신 가상 이름을 입력하세요.")
st.info("실제 운영 전에는 담당 교사가 학교의 개인정보 처리 절차, 외부 서비스 사용 승인, 안내문과 보관·삭제 일정을 확인해야 합니다.")

with st.sidebar:
    st.header("화면 선택")
    mode = st.radio("이용할 화면을 선택하세요.", ["학생 설문", "교사 관리"])
    st.caption("응답은 Apps Script를 통해 교사가 지정한 Google 스프레드시트에 저장됩니다.")

if mode == "학생 설문":
    fingerprint = hashlib.sha256(CLASS_CODE.encode("utf-8")).hexdigest()
    if st.session_state.get("class_access") != fingerprint:
        with st.form("class_access_form"):
            code_input = st.text_input("학급 참여 코드", type="password", max_chars=100)
            entered = st.form_submit_button("설문 시작하기")
        if entered:
            now_access = time.time()
            if now_access < st.session_state.get("class_wait_until", 0):
                st.error("잠시 기다린 뒤 다시 시도해 주세요.")
            elif same_secret(code_input, CLASS_CODE):
                st.session_state.class_access = fingerprint
                st.session_state.class_failures = 0
                st.rerun()
            else:
                attempts = st.session_state.get("class_failures", 0) + 1
                st.session_state.class_failures = attempts
                if attempts >= 5:
                    st.session_state.class_wait_until = now_access + 60
                    st.session_state.class_failures = 0
                st.error("참여 코드가 일치하지 않습니다. 선생님께 확인해 주세요.")
        st.caption("참여 코드는 학생 개인의 신원을 확인하는 기능이 아닙니다.")
        st.stop()
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
            except DuplicateResponse:
                st.warning("같은 학년·반·번호로 이미 제출한 응답이 있습니다. 수정하려면 선생님께 문의해 주세요.")
            except BridgeError as exc:
                st.error(str(exc))
            else:
                st.success("설문 응답을 저장했습니다. 감사합니다!")
                st.caption("응답 내용 변경은 선생님께 문의해 주세요. 이 설문은 학번의 실제 소유자를 인증하지는 않습니다.")
else:
    st.subheader("교사 관리")
    st.caption("교사 비밀번호는 선생님이 Streamlit Secrets에 설정한 값입니다.")
    password_fingerprint = hashlib.sha256(ADMIN_PASSWORD.encode("utf-8")).hexdigest()
    teacher_ok = (
        st.session_state.get("teacher_authenticated") == password_fingerprint
        and time.time() < st.session_state.get("teacher_expires", 0)
    )
    if not teacher_ok:
        with st.form("teacher_login"):
            password = st.text_input("교사 비밀번호", type="password", max_chars=200)
            login = st.form_submit_button("로그인")
        if login:
            now_login = time.time()
            if now_login < st.session_state.get("teacher_wait_until", 0):
                st.error("로그인 시도가 많습니다. 잠시 기다린 뒤 다시 시도해 주세요.")
            elif same_secret(password, ADMIN_PASSWORD):
                st.session_state.teacher_authenticated = password_fingerprint
                st.session_state.teacher_expires = now_login + 1800
                st.session_state.teacher_failures = 0
                st.rerun()
            else:
                attempts = st.session_state.get("teacher_failures", 0) + 1
                st.session_state.teacher_failures = attempts
                if attempts >= 5:
                    st.session_state.teacher_wait_until = now_login + 60
                    st.session_state.teacher_failures = 0
                st.error("비밀번호가 일치하지 않습니다.")
        st.stop()
    if st.button("교사 로그아웃"):
        st.session_state.teacher_authenticated = False
        st.rerun()
    st.warning("사용을 마치면 로그아웃하세요. 내려받은 파일에도 학생 개인정보가 들어 있습니다.")
    try:
        df = read_responses()
    except BridgeError as exc:
        st.error(str(exc))
        st.stop()
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
            labels = {str(r["id"]): f'{r["학년"]}학년 {r["반"]}반 {r["번호"]}번 · {r["이름"]}' for _, r in df.iterrows()}
            with st.form("delete_one"):
                chosen = st.selectbox("삭제할 응답", list(labels), format_func=lambda x: labels[x], index=None, placeholder="응답을 선택하세요.")
                confirmed = st.checkbox("선택한 응답을 영구 삭제하는 것을 확인했습니다.")
                delete = st.form_submit_button("선택한 응답 삭제")
            if delete:
                if chosen is None or not confirmed:
                    st.error("삭제할 응답을 선택하고 확인란을 체크하세요.")
                else:
                    try:
                        delete_response(chosen)
                    except BridgeError as exc:
                        st.error(str(exc))
                    else:
                        st.rerun()
