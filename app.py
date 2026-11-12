import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st
from dotenv import load_dotenv

# ---------- Setup ----------
load_dotenv(Path(__file__).parent / ".env")
st.set_page_config(page_title="Urban Pulse NYC 311", layout="wide")


def run_query(sql, params=None):
    """Run a SQL query on PostgreSQL and return the result as a DataFrame."""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME"),
    )
    cursor = conn.cursor()
    cursor.execute(sql, params)
    columns = [c[0] for c in cursor.description]
    df = pd.DataFrame(cursor.fetchall(), columns=columns)
    conn.close()
    return df


@st.cache_data
def load_filter_options():
    boroughs = run_query("SELECT DISTINCT borough FROM service_requests ORDER BY borough")
    complaints = run_query("""SELECT complaint_type, COUNT(*) AS n FROM service_requests
                              GROUP BY complaint_type ORDER BY n DESC""")
    dates = run_query("""SELECT MIN(created_date)::date AS first_day,
                                MAX(created_date)::date AS last_day FROM service_requests""")
    return (boroughs["borough"].tolist(), complaints["complaint_type"].tolist(),
            dates["first_day"][0], dates["last_day"][0])


@st.cache_data
def load_data(start, end, boroughs, complaints):
    # %s placeholders = parameterized query (safe for user-selected filters)
    sql = """SELECT * FROM service_requests
             WHERE created_date >= %s
               AND created_date < %s + INTERVAL '1 day'
               AND borough = ANY(%s)
               AND complaint_type = ANY(%s)"""
    return run_query(sql, (start, end, list(boroughs), list(complaints)))


# ---------- Load filter choices (with connection-error handling) ----------
try:
    all_boroughs, all_complaints, first_day, last_day = load_filter_options()
except Exception as e:
    st.error(f"Could not connect to the database. Check PostgreSQL and your .env file.\n\n{e}")
    st.stop()

# ---------- Sidebar filters ----------
st.sidebar.header("Filters")
date_range = st.sidebar.date_input("Created date", (first_day, last_day),
                                   min_value=first_day, max_value=last_day)
boroughs = st.sidebar.multiselect("Borough", all_boroughs, default=all_boroughs)
complaints = st.sidebar.multiselect("Complaint type (empty = all)", all_complaints)

if len(date_range) != 2:
    st.info("Pick an end date to apply the date filter.")
    st.stop()

start, end = date_range
df = load_data(start, end, tuple(boroughs), tuple(complaints or all_complaints))

st.title("Urban Pulse: NYC 311 Service Requests")
st.caption(f"Showing {len(df):,} requests from {start} to {end}")

if df.empty:
    st.warning("No requests match these filters. Try widening them.")
    st.stop()

# ---------- Five KPIs ----------
hours = df["resolution_hours"].dropna()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total requests", f"{df['unique_key'].nunique():,}")
k2.metric("Recorded closure", f"{df['is_closed'].mean() * 100:.1f}%")
k3.metric("Open requests", f"{(~df['is_closed']).sum():,}")
k4.metric("Median resolution", f"{hours.median():.1f} h" if len(hours) else "n/a")
k5.metric("Over 72 hours", f"{(hours > 72).mean() * 100:.1f}%" if len(hours) else "n/a")

st.caption("Closure = a closed date is recorded (not citizen satisfaction). "
           "72 hours is a project-defined cut-off, not an official service standard.")

# ---------- Analyst pages ----------
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Overview", "Time patterns", "Resolution", "Map", "Data preview"])

with tab1:
    top10 = df["complaint_type"].value_counts().head(10).reset_index()
    top10.columns = ["complaint_type", "requests"]
    fig = px.bar(top10, x="requests", y="complaint_type", orientation="h",
                 title="Top 10 complaint types")
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, width="stretch")

    col1, col2 = st.columns(2)
    agency = df["agency"].value_counts().reset_index()
    agency.columns = ["agency", "requests"]
    col1.plotly_chart(px.bar(agency, x="agency", y="requests", title="Agency workload"),
                      width="stretch")

    borough = df["borough"].value_counts().reset_index()
    borough.columns = ["borough", "requests"]
    col2.plotly_chart(px.bar(borough, x="borough", y="requests", title="Requests by borough"),
                      width="stretch")

    status = df["status"].value_counts().reset_index()
    status.columns = ["status", "requests"]
    st.plotly_chart(px.pie(status, names="status", values="requests",
                           title="Request status"), width="stretch")

with tab2:
    daily = df.groupby(df["created_date"].dt.date).size().reset_index(name="requests")
    daily.columns = ["day", "requests"]
    st.plotly_chart(px.line(daily, x="day", y="requests", markers=True,
                            title="Requests per day"), width="stretch")

    col1, col2 = st.columns(2)
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday = df["weekday"].value_counts().reindex(order, fill_value=0).reset_index()
    weekday.columns = ["weekday", "requests"]
    col1.plotly_chart(px.bar(weekday, x="weekday", y="requests", title="Requests by weekday"),
                      width="stretch")

    hourly = df["hour"].value_counts().sort_index().reset_index()
    hourly.columns = ["hour", "requests"]
    col2.plotly_chart(px.bar(hourly, x="hour", y="requests", title="Requests by hour"),
                      width="stretch")

with tab3:
    closed = df.dropna(subset=["resolution_hours"])
    if closed.empty:
        st.info("No closed requests with valid resolution time for these filters.")
    else:
        st.plotly_chart(px.histogram(closed[closed["resolution_hours"] <= 200],
                                     x="resolution_hours", nbins=50,
                                     title="Resolution time (hours, up to 200 h)"),
                        width="stretch")

        col1, col2 = st.columns(2)
        by_type = (closed.groupby("complaint_type")["resolution_hours"]
                   .agg(["count", "median"]).query("count >= 50")
                   .sort_values("median", ascending=False).head(15).reset_index())
        fig = px.bar(by_type, x="median", y="complaint_type", orientation="h",
                     title="Median hours by complaint type (n >= 50)")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        col1.plotly_chart(fig, width="stretch")

        by_agency = (closed.groupby("agency")["resolution_hours"].median()
                     .sort_values(ascending=False).reset_index())
        col2.plotly_chart(px.bar(by_agency, x="agency", y="resolution_hours",
                                 title="Median hours by agency"), width="stretch")

        n_out = int(closed["is_outlier"].sum())
        st.write(f"**IQR outliers:** {n_out:,} of {len(closed):,} closed requests "
                 f"({n_out / len(closed) * 100:.1f}%). Flagged for review, not deleted.")

with tab4:
    points = df.dropna(subset=["latitude", "longitude"])
    st.write(f"{len(points):,} requests have usable coordinates "
             f"(showing up to 5,000 random points).")
    if not points.empty:
        st.map(points.sample(min(5000, len(points)), random_state=1),
               latitude="latitude", longitude="longitude", size=20)

with tab5:
    st.dataframe(df.head(500), width="stretch")
    st.download_button("Download filtered data (CSV)",
                       df.to_csv(index=False), "nyc311_filtered.csv", "text/csv")
