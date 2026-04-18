import streamlit as st
import requests
from datetime import datetime

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="NHL Scanner Pro", layout="centered")

# --- SYSTÈME D'ÉTOILES (75+ = 6 etoiles / 65+ = 5 etoiles) ---
def obtenir_etoiles(note):
    if note >= 75: return "⭐⭐⭐⭐⭐⭐"
    elif note >= 65: return "⭐⭐⭐⭐⭐"
    elif note >= 50: return "⭐⭐⭐⭐"
    elif note >= 35: return "⭐⭐⭐"
    else: return "⭐⭐"

# --- 1. TON ALGO ORIGINAL (LOGIQUE 40/20/15/20/5) ---
def calculer_score_final(dyn, h5, l10_loc, reb_exp, opp_gaa_10, avg_h2h, pp_val, pk_opp, w_h2h):
    score = (dyn['ratio'] * 100 * 0.40) 
    score += (h5 * 20 * 0.20) 
    score += (l10_loc * 10 * 0.15)
    score += (min(opp_gaa_10 / 4.5, 1) * 100 * 0.20) 
    score += (w_h2h * 5 * 0.05)
    
    pp_calc = pp_val if isinstance(pp_val, (int, float)) else 0
    pk_calc = pk_opp if isinstance(pk_opp, (int, float)) else 100
    if pp_calc > 22 and pk_calc < 78: score += 10
    if avg_h2h > 5.8: score += 5
    if reb_exp: score += 10 
    return round(score, 1)

# --- 2. RÉCUPÉRATION DES DONNÉES ---
@st.cache_data(ttl=3600)
def obtenir_stats_ligue():
    try:
        url = "https://api-web.nhle.com/v1/standings/now"
        data = requests.get(url).json().get('standings', [])
        return {t['teamAbbrev']['default']: {'pp': round(t.get('powerPlayPct', 0)*100, 1), 'pk': round(t.get('penaltyKillPct', 0)*100, 1)} for t in data}
    except: return {}

def verifier_rebond_expert(logs):
    recent = logs[:15]
    if len(recent) < 2 or recent[0]['points'] > 0: return False
    for i in range(len(recent) - 1):
        if recent[i]['points'] == 0 and recent[i+1]['points'] == 0: return False
    return True

def obtenir_matchup_data(team_a, team_b):
    try:
        url = f"https://api-web.nhle.com/v1/club-schedule-season/{team_a}/now"
        res = requests.get(url).json()
        past = [g for g in res.get('games', []) if g['gameState'] == 'OFF']
        gaa_10 = round(sum(g['awayTeam']['score'] if g['homeTeam']['abbrev'] == team_a else g['homeTeam']['score'] for g in past[:10]) / 10, 2)
        h2h = [g for g in past if (g['homeTeam']['abbrev'] == team_b or g['awayTeam']['abbrev'] == team_b)][:10]
        w_h2h = sum(1 for g in h2h if (g['homeTeam']['abbrev'] == team_a and g['homeTeam']['score'] > g['awayTeam']['score']) or (g['awayTeam']['abbrev'] == team_a and g['awayTeam']['score'] > g['homeTeam']['score']))
        ga_vs = round(sum(g['homeTeam']['score'] if g['awayTeam']['abbrev'] == team_a else g['awayTeam']['score'] for g in h2h) / len(h2h), 2) if h2h else 3.0
        return gaa_10, w_h2h, len(h2h), 5.8, ga_vs
    except: return 3.2, 0, 0, 5.5, 3.0

# --- 3. INTERFACE ---
st.title("🏒 NHL SCANNER PRO")
date_match = st.date_input("Date du scan :", value=datetime.strptime("2026-04-18", "%Y-%m-%d"))

if st.button('LANCER LE SCAN 🚀', use_container_width=True):
    stats_ligue = obtenir_stats_ligue()
    url_score = f"https://api-web.nhle.com/v1/score/{date_match}"
    
    with st.spinner('Analyse en cours...'):
        games = requests.get(url_score).json().get('games', [])
        results_global = []

        for g in games:
            h, a = g['homeTeam']['abbrev'], g['awayTeam']['abbrev']
            memo = {h: obtenir_matchup_data(h, a), a: obtenir_matchup_data(a, h)}
            
            for team in [h, a]:
                opp = a if team == h else h
                loc_label = "DOMICILE" if team == h else "EXTÉRIEUR"
                try:
                    roster = requests.get(f"https://api-web.nhle.com/v1/roster/{team}/current").json()
                    for p in (roster.get('forwards', []) + roster.get('defensemen', [])):
                        try:
                            logs = requests.get(f"https://api-web.nhle.com/v1/player/{p['id']}/game-log/now").json().get('gameLog', [])
                            if len(logs) < 15: continue
                            
                            dyn = {"ratio": sum(1 for m in logs[:20] if m['points'] > 0)/20, "count": sum(1 for m in logs[:20] if m['points'] > 0)}
                            reb = verifier_rebond_expert(logs)
                            l10_loc = sum(1 for m in [m for m in logs if m['homeRoadFlag'] == ('H' if team == h else 'R')][:10] if m['points'] > 0)
                            h5 = sum(1 for m in [m for m in logs if m['opponentAbbrev'] == opp][:5] if m['points'] > 0)
                            m_t, m_o = memo[team], memo[opp]
                            
                            note = calculer_score_final(dyn, h5, l10_loc, reb, m_o[0], m_t[3], stats_ligue.get(team, {}).get('pp', 0), stats_ligue.get(opp, {}).get('pk', 0), m_t[1])
                            
                            if note > 30:
                                results_global.append({
                                    'id': p['id'],
                                    'nom': f"{p['firstName']['default']} {p['lastName']['default']}",
                                    'team': team, 'opp': opp, 'note': note, 'reb': reb, 
                                    'dyn_count': dyn['count'], 'h5': h5, 'gaa': m_o[0], 
                                    'ga_h2h': m_o[4], 'w_h2h': m_t[1], 't_h2h': m_t[2],
                                    'loc': loc_label, 'l10_loc': l10_loc, 'avg': m_t[3]
                                })
                        except: continue
                except: continue

        if results_global:
            top_20 = sorted(results_global, key=lambda x: x['note'], reverse=True)[:20]
            st.success(f"Scan terminé : {len(top_20)} joueurs trouvés.")
            
            for p in top_20:
                with st.container(border=True):
                    col_img, col_info = st.columns([1, 2])
                    
                    with col_img:
                        url_photo = f"https://assets.nhle.com/mugs/nhl/latest/{p['id']}.png"
                        st.image(url_photo, width=110)
                    
                    with col_info:
                        st.markdown(f"## {p['nom'].upper()}")
                        st.markdown(f"<h3 style='color:#FFD700; margin-bottom:0;'>{obtenir_etoiles(p['note'])}</h3>", unsafe_allow_html=True)
                        st.caption(f"Note : {p['note']}/100 | {p['team']} vs {p['opp']}")

                    st.markdown("---")
                    
                    # --- STATS BRUTES ---
                    st.write(f"📈 **RÉGULARITÉ** : {p['dyn_count']}/20")
                    
                    reb_txt = "OUI" if p['reb'] else "NON"
                    st.write(f"🎯 **PATTERN REBOND** : {reb_txt}")
                    
                    st.write(f"⚔️ **FACE-A-FACE** : {p['h5']}/5 | Victoires Équipe : {p['w_h2h']}/{p['t_h2h']}")
                    
                    st.write(f"🛡️ **DÉFENSE ADVERSE** : {p['gaa']} GA/G | vs {p['team']} : {p['ga_h2h']} GA/G")
                    
                    st.write(f"🏟️ **CONTEXTE** : {p['loc']} ({p['l10_loc']}/10) | Matchup {p['avg']} G/G")

        else:
            st.error("Aucun résultat.")
