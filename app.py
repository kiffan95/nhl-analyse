import streamlit as st
import requests
from datetime import datetime

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(
    page_title="ANALYSE NHL",
    page_icon="🏒",
    layout="centered"
)

# --- CACHER LE RESTE ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- SYSTÈME D'ÉTOILES ---
def obtenir_etoiles(note):
    if note >= 75: return "⭐⭐⭐⭐⭐⭐"
    elif note >= 65: return "⭐⭐⭐⭐⭐"
    elif note >= 55: return "⭐⭐⭐⭐"
    elif note >= 45: return "⭐⭐⭐"
    else: return "⭐⭐"

# --- 1. TON ALGO AVEC PONDÉRATION MISE À JOUR (40/25/10/20/5) ---
def calculer_score_final(dyn, ratio_h2h_carriere, l10_loc, reb_exp, opp_gaa_10, avg_h2h, pp_val, pk_opp, w_h2h):
    # Régularité 20 matchs (40%)
    score = (dyn['ratio'] * 100 * 0.40) 
    # H2H TOUTES SAISONS (25%) - ratio_h2h_carriere est déjà un ratio (pts/matchs)
    score += (min(ratio_h2h_carriere, 1.2) / 1.2 * 100 * 0.25) 
    # Localisation (10%)
    score += (l10_loc * 10 * 0.10)
    # Défense adverse (20%)
    score += (min(opp_gaa_10 / 4.5, 1) * 100 * 0.20) 
    # Victoires H2H (5%)
    score += (w_h2h * 5 * 0.05)
    
    # BONUS
    if (pp_val or 0) > 22 and (pk_opp or 100) < 78: score += 10
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

def obtenir_h2h_toutes_saisons(player_id, opp_abbrev):
    """Va chercher le cumul de points en carrière contre l'adversaire"""
    try:
        url = f"https://api-web.nhle.com/v1/player/{player_id}/stats/now"
        data = requests.get(url).json()
        for split in data.get('splits', []):
            if split.get('opponentAbbrev') == opp_abbrev:
                gp = split.get('gamesPlayed', 0)
                pts = split.get('points', 0)
                ratio = pts / gp if gp > 0 else 0
                return ratio, f"{pts} pts en {gp} matchs"
        return 0, "0 pts / 0 m"
    except: return 0, "N/A"

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
        ga_vs = round(sum(g['homeTeam']['score'] if g['awayTeam']['abbrev'] == team_a else g['awayTeam']['score'] for g in h2h) / len(h2h) , 2) if h2h else 3.0
        return gaa_10, w_h2h, len(h2h), 5.8, ga_vs
    except: return 3.2, 0, 0, 5.8, 3.0

# --- 3. INTERFACE ---
st.title("🏒 ANALYSE POINTEURS NHL")
date_match = st.date_input("Date du scan :", value=datetime.now())

if st.button('LANCER LE SCAN 🚀', use_container_width=True):
    stats_ligue = obtenir_stats_ligue()
    # Formatage de la date pour l'API
    date_str = date_match.strftime("%Y-%m-%d")
    url_score = f"https://api-web.nhle.com/v1/score/{date_str}"
    
    with st.spinner('Analyse des carrières en cours...'):
        resp = requests.get(url_score)
        if resp.status_code != 200:
            st.error("Impossible de joindre l'API NHL.")
            st.stop()
        
        games = resp.json().get('games', [])
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
                            # 1. Stats récentes (Logique de base)
                            logs = requests.get(f"https://api-web.nhle.com/v1/player/{p['id']}/game-log/now").json().get('gameLog', [])
                            if len(logs) < 15: continue
                            
                            p20 = sum(1 for m in logs[:20] if m['points'] > 0)
                            l10_loc = sum(1 for m in [m for m in logs if m['homeRoadFlag'] == ('H' if team == h else 'R')][:10] if m['points'] > 0)
                            reb = verifier_rebond_expert(logs)
                            
                            # 2. H2H CARRIÈRE COMPLÈTE (Toutes saisons)
                            ratio_h2h, label_h2h = obtenir_h2h_toutes_saisons(p['id'], opp)
                            
                            m_t, m_o = memo[team], memo[opp]
                            note = calculer_score_final({"ratio": p20/20}, ratio_h2h, l10_loc, reb, m_o[0], m_t[3], 
                                                        stats_ligue.get(team, {}).get('pp'), stats_ligue.get(opp, {}).get('pk'), m_t[1])
                            
                            if note > 35:
                                results_global.append({
                                    'id': p['id'], 'nom': f"{p['firstName']['default']} {p['lastName']['default']}",
                                    'team': team, 'opp': opp, 'note': note, 'reb': reb, 
                                    'p20': f"{p20}/20", 'h2h_txt': label_h2h, 'gaa': m_o[0], 
                                    'loc': loc_label, 'l10_loc': l10_loc
                                })
                        except: continue
                except: continue

        if results_global:
            top_20 = sorted(results_global, key=lambda x: x['note'], reverse=True)[:20]
            st.success(f"Scan terminé : {len(top_20)} joueurs trouvés.")
            for p in top_20:
                with st.container(border=True):
                    col_img, col_info = st.columns([1, 2])
                    with col_img: st.image(f"https://assets.nhle.com/mugs/nhl/latest/{p['id']}.png", width=110)
                    with col_info:
                        st.markdown(f"## {p['nom'].upper()}")
                        st.markdown(f"<h3 style='color:#FFD700;'>{obtenir_etoiles(p['note'])}</h3>", unsafe_allow_html=True)
                        st.caption(f"Note : {p['note']}/100 | {p['team']} vs {p['opp']}")
                    st.write(f"📈 **RÉGULARITÉ** : ➤ {p['p20']} (20 derniers) | ➤ {p['l10_loc']}/10 à {p['loc']}")
                    st.write(f"📜 **HISTORIQUE CARRIÈRE vs {p['opp']}** : ➤ {p['h2h_txt']}")
                    if p['reb']: st.info("🎯 Pattern de rebond détecté")
