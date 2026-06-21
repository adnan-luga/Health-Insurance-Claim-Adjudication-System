import streamlit as st
import requests
import os
import json

# Configuration
INGESTION_URL = os.getenv("INGESTION_API_URL", "http://ingestion_api:8080/api/v1/policies")
ADJUDICATION_URL = os.getenv("ADJUDICATION_API_URL", "http://adjudication_api:8081/api/v1/policies")

st.set_page_config(page_title="Adjudication Engine", page_icon="🏥", layout="wide")

# Custom CSS for aesthetics
st.markdown("""
<style>
    .metric-card {
        background-color: #1e2a3a;
        border-radius: 12px;
        padding: 24px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .metric-card h3 {
        color: #a0aab8 !important;
        font-size: 0.95rem;
        font-weight: 500;
        margin-bottom: 8px;
    }
    .metric-card h2 {
        color: #ffffff !important;
        font-size: 1.8rem;
        font-weight: 700;
        margin: 0;
    }
    .status-approved { color: #4caf50; font-weight: bold; }
    .status-partial { color: #ff9800; font-weight: bold; }
    .status-denied { color: #f44336; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Ingestion Dashboard 📥", "Claims Adjudication ⚖️"])

if page == "Ingestion Dashboard 📥":
    st.title("Policy Ingestion Engine 📥")
    st.write("Upload a medical policy wording document (PDF) to automatically extract and compile the ruleset into the Postgres database.")
    
    with st.form("ingestion_form"):
        policy_id = st.text_input("Policy ID", value="POL-2026-A1")
        uploaded_file = st.file_uploader("Upload Policy Document (PDF)", type=["pdf"])
        submit_button = st.form_submit_button("Compile Policy")
        
    if submit_button:
        if not uploaded_file:
            st.error("Please upload a PDF document.")
        else:
            with st.spinner("Extracting rules, exclusions, and endorsements... This may take a minute."):
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                data = {"policy_id": policy_id}
                try:
                    response = requests.post(f"{INGESTION_URL}/ingest", files=files, data=data, timeout=300)
                    if response.status_code == 200:
                        res = response.json()
                        st.success("✅ Policy successfully compiled and saved to database!")
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Coverage Rules", res.get("rule_count", 0))
                        with col2:
                            st.metric("Exclusions", res.get("exclusion_count", 0))
                        with col3:
                            st.metric("Endorsements", res.get("endorsement_count", 0))
                            
                        with st.expander("View Compiled JSON Ruleset"):
                            # Fetch the compiled rules
                            rules_resp = requests.get(f"{INGESTION_URL}/{policy_id}/rules")
                            if rules_resp.status_code == 200:
                                st.json(rules_resp.json())
                            else:
                                st.warning("Ruleset compiled, but could not fetch JSON preview.")
                    else:
                        st.error(f"Ingestion failed: {response.text}")
                except Exception as e:
                    st.error(f"Connection error: {str(e)}")

elif page == "Claims Adjudication ⚖️":
    st.title("Claims Adjudication Engine ⚖️")
    st.write("Upload a medical invoice. The engine will extract line items and deterministically adjudicate them against the compiled policy ruleset.")
    
    with st.form("adjudication_form"):
        col1, col2 = st.columns(2)
        with col1:
            policy_id = st.text_input("Policy ID", value="POL-2026-A1")
        with col2:
            member_id = st.text_input("Member ID", value="MEM-987654")
            
        uploaded_file = st.file_uploader("Upload Medical Invoice (PDF)", type=["pdf"])
        submit_button = st.form_submit_button("Adjudicate Claim")
        
    if submit_button:
        if not uploaded_file:
            st.error("Please upload an invoice PDF.")
        else:
            with st.spinner("Extracting invoice and running deterministic adjudication..."):
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                data = {"policy_id": policy_id, "member_id": member_id}
                try:
                    response = requests.post(f"{ADJUDICATION_URL}/process-pdf", files=files, data=data, timeout=300)
                    if response.status_code == 200:
                        res = response.json()
                        st.success("✅ Claim successfully adjudicated!")
                        
                        # Summary metrics
                        st.markdown("### Total Summary")
                        col1, col2, col3 = st.columns(3)
                        
                        billed_total = sum(float(r.get("billed_amount", 0)) for r in res.get("results", []))
                        
                        with col1:
                            st.markdown(f'<div class="metric-card"><h3>Total Billed</h3><h2>AED {billed_total:.2f}</h2></div>', unsafe_allow_html=True)
                        with col2:
                            total_insurer = float(res.get("total_insurer_paid", 0))
                            st.markdown(f'<div class="metric-card"><h3>Total Insurer Pays</h3><h2 style="color: #2e7d32;">AED {total_insurer:.2f}</h2></div>', unsafe_allow_html=True)
                        with col3:
                            total_member = float(res.get("total_member_paid", 0))
                            st.markdown(f'<div class="metric-card"><h3>Total Member Owes</h3><h2 style="color: #c62828;">AED {total_member:.2f}</h2></div>', unsafe_allow_html=True)
                        
                        st.markdown("---")
                        st.markdown("### Line Item Details & Audit Trail")
                        
                        for i, result in enumerate(res.get("results", [])):
                            decision = result.get("decision", "UNKNOWN")
                            if decision == "APPROVED":
                                status_class = "status-approved"
                                icon = "✅"
                            elif decision == "PARTIALLY_APPROVED":
                                status_class = "status-partial"
                                icon = "⚠️"
                            else:
                                status_class = "status-denied"
                                icon = "❌"
                                
                            with st.expander(f"{icon} Claim ID: {result.get('claim_id')} - {decision.replace('_', ' ')}"):
                                st.markdown(f"**Status**: <span class='{status_class}'>{decision}</span>", unsafe_allow_html=True)
                                if result.get("denial_reason"):
                                    st.error(f"Reason: {result['denial_reason']}")
                                
                                # Financial Breakdown
                                mcol1, mcol2, mcol3, mcol4 = st.columns(4)
                                mcol1.metric("Billed", f"AED {result.get('billed_amount', 0)}")
                                mcol2.metric("Eligible", f"AED {result.get('eligible_amount', 0)}")
                                mcol3.metric("Insurer Pays", f"AED {result.get('insurer_pays', 0)}")
                                mcol4.metric("Member Owes", f"AED {result.get('member_owes', 0)}")
                                
                                # Detailed Audit Trail
                                st.markdown("#### Deterministic Audit Trail")
                                for step in result.get("audit_trail", []):
                                    st.info(f"**Step: {step.get('step')}**\n\n{step.get('description')}")
                                    
                    else:
                        st.error(f"Adjudication failed: {response.text}")
                except Exception as e:
                    st.error(f"Connection error: {str(e)}")
