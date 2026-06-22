import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import altair as alt

# 스트림릿 페이지 설정 (아이콘 및 반응형 레이아웃 구성)
st.set_page_config(
    page_title="삼성전자 주가 & 이슈 분석기",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="expanded"
)

# 사이드바 설정
st.sidebar.title("📈 주식 분석기")
st.sidebar.markdown("국내 주요 종목의 가격 흐름과 당일/전일 뉴스 헤드라인을 분석하는 도구입니다.")
st.sidebar.caption("Powered by Naver FChart & Google News")

# ==========================================
# 주식 & 이슈 분석기 비즈니스 로직 및 컴포넌트
# ==========================================

def get_stock_data(symbol, count=100):
    """네이버 금융 FChart XML API를 이용해 일별 시세 데이터 획득"""
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count={count}&requestType=0"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            import xml.etree.ElementTree as ET
            # Decode to unicode string using EUC-KR encoding
            xml_text = r.content.decode('euc-kr', errors='replace')
            # Remove XML declaration to prevent multi-byte encoding error in standard ElementTree
            if xml_text.startswith("<?xml"):
                idx = xml_text.find("?>")
                if idx != -1:
                    xml_text = xml_text[idx+2:]
            
            root = ET.fromstring(xml_text.strip())
            data = []
            for item in root.findall('.//item'):
                row = item.attrib['data'].split('|')
                # Date(YYYYMMDD), Open, High, Low, Close, Volume
                if len(row) >= 6:
                    data.append({
                        'Date': row[0],
                        'Open': float(row[1]),
                        'High': float(row[2]),
                        'Low': float(row[3]),
                        'Close': float(row[4]),
                        'Volume': int(row[5])
                    })
            df = pd.DataFrame(data)
            if not df.empty:
                df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d')
                df = df.sort_values('Date').reset_index(drop=True)
                return df
    except Exception as e:
        st.error(f"주가 조회 중 오류 발생: {str(e)}")
    return None


def get_news_for_date(keyword, target_date):
    """구글 뉴스 RSS를 사용하여 특정 날짜의 하루 전(Date - 1)과 당일(Date) 뉴스 헤드라인 검색"""
    from datetime import timedelta
    import xml.etree.ElementTree as ET
    
    # after/before는 경계값을 포함하지 않으므로 하루 전과 당일을 포함하도록 기간 설정
    # after: target_date - 2일 (초과이므로 target_date-1일부터 포함)
    # before: target_date + 1일 (미만이므로 target_date일까지 포함)
    start_date = target_date - timedelta(days=2)
    end_date = target_date + timedelta(days=1)
    
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    
    query = f"{keyword} after:{start_str} before:{end_str}"
    quoted_query = requests.utils.quote(query)
    
    url = f"https://news.google.com/rss/search?q={quoted_query}&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            news_list = []
            for item in root.findall('.//item'):
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                pubDate = item.find('pubDate').text if item.find('pubDate') is not None else ""
                source = item.find('source').text if item.find('source') is not None else ""
                
                clean_title = title
                if " - " in title:
                    clean_title = " - ".join(title.split(" - ")[:-1])
                
                news_list.append({
                    'title': clean_title,
                    'link': link,
                    'pubDate': pubDate,
                    'source': source
                })
            return news_list
    except Exception:
        pass
    return []


def get_investor_trading_data(symbol):
    """네이버 금융 투자자별 매매동향 페이지에서 외국인/기관 매매 데이터를 수집"""
    url = f"https://finance.naver.com/item/frgn.naver?code={symbol}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            import io
            # Force EUC-KR decoding
            html_content = r.content.decode('euc-kr', errors='replace')
            df_list = pd.read_html(io.StringIO(html_content))
            if len(df_list) > 3:
                df = df_list[3]
                # Flatten MultiIndex columns
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] + "_" + col[1] if col[0] != col[1] else col[0] for col in df.columns]
                
                # Drop NaN dates
                df = df.dropna(subset=[df.columns[0]])
                df = df.reset_index(drop=True)
                
                # Rename to English columns for safety
                df.columns = ['Date', 'Close', 'Change_text', 'Change_Pct', 'Volume', 'Institution_Net', 'Foreign_Net', 'Foreign_Shares', 'Foreign_Ratio']
                # Clean numerical columns
                df['Institution_Net'] = pd.to_numeric(df['Institution_Net'], errors='coerce').fillna(0).astype(int)
                df['Foreign_Net'] = pd.to_numeric(df['Foreign_Net'], errors='coerce').fillna(0).astype(int)
                return df
    except Exception as e:
        st.error(f"투자자 매매 동향 데이터 수집 중 오류 발생: {str(e)}")
    return None


def render_stock_analysis(stock_name, stock_code, days_count):
    """지정된 종목의 주가 및 관련 뉴스를 렌더링하는 함수"""
    with st.spinner(f"네이버 금융에서 {stock_name} 주가 정보를 수집하는 중..."):
        df = get_stock_data(stock_code, count=days_count)
        
    if df is not None and not df.empty:
        # 주가 계산 변수 생성
        df['Change'] = df['Close'].diff()
        df['Change_Pct'] = (df['Close'].pct_change() * 100).round(2)
        
        # 이동평균선(SMA) 및 지지/저항선 계산
        df['SMA_5'] = df['Close'].rolling(window=5).mean()
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        support_price = int(df['Low'].min())
        resistance_price = int(df['High'].max())
        
        # 최신 가격 데이터 메트릭 표시
        latest_row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) > 1 else latest_row
        
        change_val = latest_row['Close'] - prev_row['Close']
        change_pct = ((latest_row['Close'] - prev_row['Close']) / prev_row['Close'] * 100) if prev_row['Close'] > 0 else 0.0
        
        # 주가 정보 메트릭 렌더링
        st.markdown("---")
        c_color = "#DC2626" if change_val > 0 else ("#2563EB" if change_val < 0 else "#64748B")
        change_sign = "+" if change_val > 0 else ""
        st.markdown(
            f"""
            <div style='display: flex; justify-content: space-between; flex-wrap: wrap; gap: 15px; margin-bottom: 20px; width: 100%;'>
                <div style='background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 15px; border-radius: 8px; flex: 1; min-width: 160px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>
                    <div style='font-size: 13px; color: #64748B; margin-bottom: 5px; font-weight: 500;'>📍 종목명</div>
                    <div style='font-size: 18px; font-weight: 700; color: #1E293B; white-space: nowrap;'>{stock_name} ({stock_code})</div>
                </div>
                <div style='background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 15px; border-radius: 8px; flex: 1; min-width: 160px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>
                    <div style='font-size: 13px; color: #64748B; margin-bottom: 5px; font-weight: 500;'>💰 현재가 (종가)</div>
                    <div style='font-size: 18px; font-weight: 700; color: #1E293B; white-space: nowrap;'>{int(latest_row['Close']):,} 원</div>
                </div>
                <div style='background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 15px; border-radius: 8px; flex: 1; min-width: 160px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>
                    <div style='font-size: 13px; color: #64748B; margin-bottom: 5px; font-weight: 500;'>📈 전일 대비</div>
                    <div style='font-size: 18px; font-weight: 700; color: {c_color}; white-space: nowrap;'>{change_sign}{int(change_val):,} 원 ({change_pct:+.2f}%)</div>
                </div>
                <div style='background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 15px; border-radius: 8px; flex: 1.2; min-width: 200px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>
                    <div style='font-size: 13px; color: #64748B; margin-bottom: 5px; font-weight: 500;'>📊 거래량</div>
                    <div style='font-size: 18px; font-weight: 700; color: #1E293B; white-space: nowrap;'>{int(latest_row['Volume']):,} 주</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        # 주가 트렌드 차트 (Candlestick Chart using Altair)
        st.markdown("### 🕯️ 주가 가격 추이 (캔들 차트)")
        
        df_chart = df.copy()
        df_chart['is_up'] = df_chart['Close'] > df_chart['Open']
        # 날짜를 YYYY-MM-DD 포맷의 문자열로 변환하여 1일 단위(영업일 기준 주말 갭 없이)로 밀착 나열
        df_chart['Date_Str'] = df_chart['Date'].dt.strftime('%Y-%m-%d')
        
        # 한국인 정서에 맞는 상승(빨강 #EF4444) / 하락(파랑 #2563EB) 색상 매핑
        color_condition = alt.condition(
            "datum.is_up", 
            alt.value("#EF4444"), # 빨강 (상승)
            alt.value("#2563EB")  # 파랑 (하락)
        )
        
        # 1일 단위 순서형(Ordinal)으로 X축 축 설정 및 모든 날짜 레이블 강제 표시
        base = alt.Chart(df_chart).encode(
            x=alt.X('Date_Str:O', title='날짜', axis=alt.Axis(labelAngle=-90, values=df_chart['Date_Str'].tolist()))
        )
        
        # 꼬리선 (High-Low)
        rule = base.mark_rule().encode(
            y=alt.Y('Low:Q', scale=alt.Scale(zero=False), title='주가 (원)'),
            y2='High:Q',
            color=color_condition
        )
        
        # 몸통 (Open-Close)
        bar = base.mark_bar(size=8).encode(
            y='Open:Q',
            y2='Close:Q',
            color=color_condition
        )
        
        # 차트 결합 및 속성 설정
        candlestick_chart = (rule + bar).properties(
            height=350
        ).interactive()
        
        # 캔들 차트 (풀 위드 표시)
        st.altair_chart(candlestick_chart, use_container_width=True)

        # 이동평균선 기반 차트 분석
        latest_close = latest_row['Close']
        latest_sma5 = latest_row['SMA_5']
        latest_sma20 = latest_row['SMA_20']
        
        prev_sma5 = prev_row['SMA_5'] if 'SMA_5' in prev_row and pd.notna(prev_row['SMA_5']) else latest_sma5
        prev_sma20 = prev_row['SMA_20'] if 'SMA_20' in prev_row and pd.notna(prev_row['SMA_20']) else latest_sma20
        
        trend_status = "횡보/혼조세 ➡️"
        trend_desc = "단기 이동평균선들이 모여 수렴하며 향후 방향성을 탐색하고 있는 흐름입니다. 지지선과 저항선 사이의 박스권 돌파 여부를 주목하세요."
        trend_color = "#64748B" # 회색
        trend_bg = "#F8FAFC"
        trend_border = "#E2E8F0"
        
        if pd.notna(latest_sma5) and pd.notna(latest_sma20):
            if latest_close >= latest_sma5 > latest_sma20:
                trend_status = "강한 상승 추세 📈"
                trend_desc = "현재 주가가 5일 및 20일 이동평균선 위에 위치해 있으며, 단기/중기 이동평균선이 정배열 상태를 구축하여 매수세가 강한 강세 국면입니다."
                trend_color = "#DC2626" # 빨강
                trend_bg = "#FEF2F2"
                trend_border = "#FCA5A5"
            elif latest_close <= latest_sma5 < latest_sma20:
                trend_status = "하락 조정 국면 📉"
                trend_desc = "현재 주가가 이평선 하방에 머물고 있으며, 단/중기 이평선이 역배열 상태입니다. 추가 하락 우려가 있으므로 주요 지지선 지지 여부를 우선 확인하십시오."
                trend_color = "#2563EB" # 파랑
                trend_bg = "#EFF6FF"
                trend_border = "#BFDBFE"
            elif prev_sma5 <= prev_sma20 and latest_sma5 > latest_sma20:
                trend_status = "골든크로스 발생 ⚡"
                trend_desc = "최근 5일 단기 이평선이 20일 중기 이평선을 위로 뚫고 오르는 골든크로스가 완성되어, 단기 추세가 반등 또는 상승세로 돌아설 가능성이 매우 높습니다."
                trend_color = "#D97706" # 오렌지
                trend_bg = "#FFFBEB"
                trend_border = "#FDE68A"
            elif prev_sma5 >= prev_sma20 and latest_sma5 < latest_sma20:
                trend_status = "데드크로스 발생 ⚠️"
                trend_desc = "최근 5일 단기 이평선이 20일 중기 이평선 아래로 꺾이는 데드크로스가 발생하여, 주가 하락 및 조정 가능성이 높아졌으니 비중 축소 혹은 관망을 권장합니다."
                trend_color = "#7C3AED" # 보라
                trend_bg = "#F5F3FF"
                trend_border = "#DDD6FE"
            elif latest_close > latest_sma20 and latest_sma5 <= latest_sma20:
                trend_status = "상승 돌파 시도 🔼"
                trend_desc = "주가가 중기 이평선(20일)을 넘어서며 추세 회복을 꾀하고 있으나, 아직 5일 이동평균선이 완전히 안착하지 못해 단기 변동성이 우려됩니다."
                trend_color = "#059669" # 초록
                trend_bg = "#ECFDF5"
                trend_border = "#A7F3D0"
            elif latest_close < latest_sma20 and latest_sma5 >= latest_sma20:
                trend_status = "하방 지지 테스트 🔽"
                trend_desc = "주가가 이평선 밑으로 소폭 이탈하며 밀렸지만, 5일 이평선이 버텨주고 있어 추가적인 지지력을 확보할 수 있는지 지켜보아야 하는 단계입니다."
                trend_color = "#0D9488" # 청록
                trend_bg = "#F0FDFA"
                trend_border = "#99F6E4"

        # 차트 아래 영역 (분석 요약 & TOP 5) 가로 배치
        col_summary, col_top5 = st.columns([5, 3])
        
        with col_summary:
            st.markdown("#### 📊 기술적 차트 분석 요약")
            sma5_text = f"{int(latest_sma5):,} 원" if pd.notna(latest_sma5) else "계산 중..."
            sma20_text = f"{int(latest_sma20):,} 원" if pd.notna(latest_sma20) else "계산 중..."
            st.markdown(
                f"""
                <div style='background-color:{trend_bg}; border: 1px solid {trend_border}; border-left: 8px solid {trend_color}; padding: 18px; border-radius: 10px; margin-top: 10px; margin-bottom: 25px;'>
                    <div style='display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;'>
                        <span style='font-size: 18px; font-weight: bold; color: #1E293B;'>현재 추세 평가: <span style='color: {trend_color};'>{trend_status}</span></span>
                        <span style='font-size: 12px; color: #64748B;'>분석 기준: 최근 {days_count}일 가격 데이터</span>
                    </div>
                    <p style='margin: 12px 0; color: #334155; line-height: 1.6; font-size: 14px;'>{trend_desc}</p>
                    <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; font-size: 13px; color: #475569; border-top: 1px dashed {trend_border}; padding-top: 12px;'>
                        <div>🟢 <b>지지선 (최저):</b> {support_price:,} 원</div>
                        <div>🔴 <b>저항선 (최고):</b> {resistance_price:,} 원</div>
                        <div>🕒 <b>5일 이평:</b> {sma5_text}</div>
                        <div>📅 <b>20일 이평:</b> {sma20_text}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
        with col_top5:
            st.markdown("#### 🏆 등락률 TOP 5 날짜")
            df_for_analysis = df.dropna().copy()
            df_for_analysis['Abs_Change_Pct'] = df_for_analysis['Change_Pct'].abs()
            top_volatile_days = df_for_analysis.nlargest(5, 'Abs_Change_Pct')
            
            volatile_table_data = []
            for _, r in top_volatile_days.iterrows():
                d_str = r['Date'].strftime('%Y-%m-%d')
                sign = "+" if r['Change_Pct'] > 0 else ""
                color = "🔴" if r['Change_Pct'] > 0 else "🔵"
                volatile_table_data.append({
                    "날짜": d_str,
                    "구분": f"{color} 상승" if r['Change_Pct'] > 0 else f"{color} 하락",
                    "등락률": f"{sign}{r['Change_Pct']}%"
                })
            st.table(pd.DataFrame(volatile_table_data))
        
        # 외국인 & 기관 매매 동향 데이터 수집 및 렌더링
        st.markdown("### 👥 외국인 & 기관 매매 동향 (최근 20영업일)")
        
        investor_df = get_investor_trading_data(stock_code)
        if investor_df is not None and not investor_df.empty:
            # 최근 20일 데이터만 사용
            df_investor_20 = investor_df.head(20).copy()
            
            # 누적 매수량 계산을 위한 날짜순 정렬 (과거 -> 현재)
            df_investor_20_sorted = df_investor_20.iloc[::-1].copy()
            df_investor_20_sorted['Institution_Cum'] = df_investor_20_sorted['Institution_Net'].cumsum()
            df_investor_20_sorted['Foreign_Cum'] = df_investor_20_sorted['Foreign_Net'].cumsum()
            
            # 차트 컬럼과 테이블 컬럼 배치
            col_investor_chart, col_investor_table = st.columns([5, 4])
            
            with col_investor_chart:
                st.markdown("##### 📈 누적 순매수 추이")
                # Melt for Altair format
                df_melted = df_investor_20_sorted.melt(
                    id_vars=['Date'], 
                    value_vars=['Institution_Cum', 'Foreign_Cum'], 
                    var_name='Investor', 
                    value_name='Cumulative_Net'
                )
                df_melted['Investor'] = df_melted['Investor'].map({'Institution_Cum': '기관', 'Foreign_Cum': '외국인'})
                
                # Altair 차트 생성
                investor_chart = alt.Chart(df_melted).mark_line(interpolate='monotone', point=True).encode(
                    x=alt.X('Date:O', title='날짜', axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y('Cumulative_Net:Q', title='누적 순매수 (주)'),
                    color=alt.Color('Investor:N', title='투자자', scale=alt.Scale(domain=['기관', '외국인'], range=['#D97706', '#2563EB'])),
                    tooltip=['Date', 'Investor', 'Cumulative_Net']
                ).properties(height=280).interactive()
                
                st.altair_chart(investor_chart, use_container_width=True)
                
            with col_investor_table:
                st.markdown("##### 📋 일별 매매 동향 (최근 10일)")
                # 테이블 표시용 데이터 프레임 가공
                table_df = df_investor_20.head(10).copy()
                table_df['Close'] = table_df['Close'].apply(lambda x: f"{int(x):,} 원" if pd.notna(x) else "-")
                table_df['Institution_Net'] = table_df['Institution_Net'].apply(lambda x: f"{int(x):+,}" if pd.notna(x) else "-")
                table_df['Foreign_Net'] = table_df['Foreign_Net'].apply(lambda x: f"{int(x):+,}" if pd.notna(x) else "-")
                
                display_df = table_df[['Date', 'Close', 'Change_Pct', 'Institution_Net', 'Foreign_Net', 'Foreign_Ratio']]
                display_df.columns = ['날짜', '종가', '등락률', '기관 순매수', '외국인 순매수', '외국인 보유율']
                st.dataframe(display_df, use_container_width=True, hide_index=True)
                
            # 매매동향 인사이트 분석
            total_foreign = df_investor_20['Foreign_Net'].sum()
            total_institution = df_investor_20['Institution_Net'].sum()
            
            # 외국인/기관 매수세 유입 특징 문자열 생성
            if total_foreign > 0 and total_institution > 0:
                buyer_insight = f"최근 20영업일 동안 **외국인(총 {total_foreign:+,}주)**과 **기관(총 {total_institution:+,}주)**이 **동반 순매수세(쌍끌이 매수)**를 보이며 강력한 수급 지지대를 형성하고 있습니다. 이는 메이저 수급이 동시에 유입되어 주가의 추가 상승 동력이 견고함을 시사합니다."
                insight_theme = "#ECFDF5" # 초록
                insight_border = "#A7F3D0"
                insight_text_color = "#047857"
            elif total_foreign > 0 and total_institution <= 0:
                buyer_insight = f"최근 20영업일 동안 **외국인은 {total_foreign:+,}주를 순매수**한 반면, **기관은 {total_institution:+,}주를 순매도**했습니다. 기관의 매도 물량을 외국인이 활발히 흡수하며 수급을 주도하고 있으며, 외국인 수급의 지속 여부가 주가 향방의 핵심 열쇠입니다."
                insight_theme = "#FFFBEB" # 오렌지/황토
                insight_border = "#FDE68A"
                insight_text_color = "#B45309"
            elif total_foreign <= 0 and total_institution > 0:
                buyer_insight = f"최근 20영업일 동안 **기관이 {total_institution:+,}주를 순매수**하며 주가 방어를 주도하고 있으나, **외국인은 {total_foreign:+,}주를 순매도**하며 차익 실현 세력을 이루고 있습니다. 기관의 매수 지지력과 외국인 매도 압력 사이의 팽팽한 힘겨루기가 이어지고 있습니다."
                insight_theme = "#FFFBEB"
                insight_border = "#FDE68A"
                insight_text_color = "#B45309"
            else:
                buyer_insight = f"최근 20영업일 동안 **외국인(총 {total_foreign:+,}주)**과 **기관(총 {total_institution:+,}주)** 모두 **동반 순매도**를 기록하며 수급적 하방 압력이 가중되고 있습니다. 당분간 보수적인 접근이 유효하며 개인 수급의 방어 여부를 관망할 필요가 있습니다."
                insight_theme = "#FEF2F2" # 빨강/연분홍
                insight_border = "#FCA5A5"
                insight_text_color = "#B91C1C"

            st.markdown(
                f"""
                <div style='background-color: {insight_theme}; border: 1px solid {insight_border}; border-left: 8px solid {insight_text_color}; padding: 18px; border-radius: 8px; margin-top: 15px; margin-bottom: 25px;'>
                    <span style='font-size: 15px; font-weight: bold; color: {insight_text_color};'>💡 수급 분석 및 인사이트 요약</span>
                    <p style='margin: 8px 0 0 0; font-size: 13.5px; color: #1E293B; line-height: 1.6;'>{buyer_insight}</p>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.warning("외국인/기관 매매동향 데이터를 불러오지 못했습니다.")
        
        # 날짜를 선택할 수 있도록 리스트 포맷 생성
        date_options = {}
        select_list = []
        
        # 일반적인 날짜 리스트 (최신순)
        all_dates_desc = df.dropna().sort_values('Date', ascending=False)
        for _, row in all_dates_desc.iterrows():
            d_str = row['Date'].strftime('%Y-%m-%d')
            day_name = ["월", "화", "수", "목", "금", "토", "일"][row['Date'].weekday()]
            change_sign = "+" if row['Change_Pct'] > 0 else ""
            label = f"{d_str} ({day_name}) | 종가: {int(row['Close']):,}원 ({change_sign}{row['Change_Pct']}%)"
            date_options[label] = row['Date']
            select_list.append(label)
            
        # 기본 선택값 설정 (가장 최근 날짜인 당일이 디폴트로 설정됩니다)
        default_index = 0
        
        # 메인 영역 중앙 배치로 날짜 선택 및 상세 분석 진행
        st.markdown("### ⚡ 주가 변동일 상세 뉴스 분석")
        
        selected_label = st.selectbox(
            "🔍 상세 분석할 날짜를 선택하세요 (최근 등락률이 컸던 날이 자동 선택됩니다):", 
            select_list,
            index=default_index,
            key=f"selectbox_date_{stock_code}" # widget ID 충돌 방지를 위해 unique key 지정
        )
        chosen_date = date_options[selected_label]
        chosen_row = df[df['Date'] == chosen_date].iloc[0]
        
        # 선택된 날짜의 가격 정보 요약 카드 (중앙 풀 위드 카드)
        c_sign = "+" if chosen_row['Change_Pct'] > 0 else ""
        c_color = "#DC2626" if chosen_row['Change_Pct'] > 0 else "#2563EB"
        bg_color = "#FEF2F2" if chosen_row['Change_Pct'] > 0 else "#EFF6FF"
        border_color = "#FCA5A5" if chosen_row['Change_Pct'] > 0 else "#BFDBFE"
        
        st.markdown(
            f"""
            <div style='background-color:{bg_color}; border: 1px solid {border_color}; border-left: 8px solid {c_color}; padding:20px; border-radius:12px; margin-top:10px; margin-bottom: 25px;'>
                <h3 style='margin:0; color:#1E293B;'>선택한 날짜: {chosen_date.strftime('%Y-%m-%d')} ({["월", "화", "수", "목", "금", "토", "일"][chosen_date.weekday()]})</h3>
                <div style='margin-top: 10px; font-size:18px; color:#334155;'>
                    종가: <b style='font-size:22px;'>{int(chosen_row['Close']):,}원</b> | 
                    전일대비: <span style='color:{c_color}; font-weight:bold; font-size:22px;'>{chosen_row['Change_Pct']:+.2f}%</span>
                </div>
            </div>
            """, 
            unsafe_allow_html=True
        )
        
        # 뉴스 로딩 및 기사 목록 표시
        with st.spinner(f"{chosen_date.strftime('%Y-%m-%d')} 하루 전 및 당일 뉴스를 검색 중..."):
            news_data = get_news_for_date(stock_name, chosen_date)
            
        if news_data:
            # 주가 영향 키워드가 포함된 뉴스를 목록 최상단에 우선 배치 (정렬)
            priority_keywords = [
                "상승", "하락", "급등", "급락", "폭등", "폭락", 
                "호재", "악재", "어닝", "쇼크", "서프라이즈", 
                "상한가", "하한가", "반등", "강세", "약세", "실적"
            ]
            news_data = sorted(
                news_data, 
                key=lambda x: 0 if any(kw in x['title'] for kw in priority_keywords) else 1
            )
            
            st.markdown("#### 📰 주요 뉴스 헤드라인 목록")
            
            # 최대 8개 기사 카드 형태로 렌더링
            for item in news_data[:8]:
                title = item['title']
                link = item['link']
                source = item['source']
                
                # 키워드 하이라이트 처리
                keywords = ["실적", "상승", "하락", "급등", "급락", "최고", "최저", "반도체", "신제품", "출시", "계약", "호재", "악재", "어닝", "쇼크", "서프라이즈"]
                highlighted_title = title
                for kw in keywords:
                    if kw in highlighted_title:
                        if kw in ["상승", "급등", "호재", "서프라이즈", "최고"]:
                            color = "#DC2626" # 빨강
                        elif kw in ["하락", "급락", "악재", "쇼크", "최저"]:
                            color = "#2563EB" # 파랑
                        else:
                            color = "#D97706" # 오렌지
                        highlighted_title = highlighted_title.replace(kw, f"<span style='color:{color}; font-weight:bold;'>{kw}</span>")
                
                st.markdown(
                    f"""
                    <div style='padding: 14px; border: 1px solid #F1F5F9; border-radius: 8px; margin-bottom: 12px; background-color: #FFFFFF; box-shadow: 0 1px 3px rgba(0,0,0,0.02);'>
                        <a href='{link}' target='_blank' style='text-decoration:none; color:#1E293B; font-weight:600; font-size:15px; display:block;'>
                            🔗 {highlighted_title}
                        </a>
                        <div style='color:#94A3B8; font-size:12px; margin-top:6px; text-align:right;'>출처: {source}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.warning("선택하신 날짜 부근에 해당하는 관련 뉴스 기사를 찾지 못했습니다.")
    else:
        st.error(f"{stock_name} 주가 정보를 불러오는 데 실패했습니다. 잠시 후 다시 시도해 주세요.")


st.title("📊 국내 주요 주식 & 이슈 분석기")
st.markdown("선택한 종목의 가격 흐름과 함께 특정 날짜에 어떤 뉴스/이슈가 있었는지 실시간으로 연계하여 주가 변동 원인을 추적합니다.")

# 분석 기간 설정
days_count = st.selectbox("분석 기간 설정", [30, 60, 90, 120], format_func=lambda x: f"최근 {x}일")

# 탭 설정
tab1, tab2 = st.tabs(["삼성전자", "SK하이닉스"])

with tab1:
    render_stock_analysis("삼성전자", "005930", days_count)

with tab2:
    render_stock_analysis("SK하이닉스", "000660", days_count)

