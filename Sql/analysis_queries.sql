/* Setup: create table service_requests */
CREATE TABLE IF NOT EXISTS service_requests (
    unique_key       BIGINT PRIMARY KEY,
    created_date     TIMESTAMP,
    agency           VARCHAR(20),
    complaint_type   VARCHAR(100),
    descriptor       VARCHAR(255),
    borough          VARCHAR(30),
    status           VARCHAR(30),
    latitude         DOUBLE PRECISION,
    longitude        DOUBLE PRECISION,
    closed_date      TIMESTAMP NULL,
    bad_dates        BOOLEAN,
    bad_location     BOOLEAN,
    is_closed        BOOLEAN,
    resolution_hours DOUBLE PRECISION NULL,
    month            INT,
    weekday          VARCHAR(10),
    hour             INT,
    is_outlier       BOOLEAN
);
------
/*Task 1: Total requests.
Findings: 99,998 unique requests (22–31 Oct 2026).*/
SELECT COUNT(DISTINCT unique_key) AS total_requests
FROM service_requests;
------
/*Task 2: Top 10 complaint types
Finding: Illegal Parking leads (17,546), 
then Noise–Residential (9,838) and HEAT/HOT WATER (9,074).)*/
SELECT complaint_type, COUNT(*) AS requests
FROM service_requests
GROUP BY complaint_type
ORDER BY requests DESC
LIMIT 10;
------
/* Task 3: Agency workload (with %) 
Finding: NYPD handles 44.8% of all requests and HPD 24.1%. 
Two agencies carry about 70% of the workload.*/
SELECT agency, COUNT(*) AS requests,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM service_requests
GROUP BY agency
ORDER BY requests DESC;
------
/* Task 4: Requests by borough
Finding:Brooklyn has the most requests (32,715), 
then Queens (22,701).*/
SELECT borough, COUNT(*) AS requests
FROM service_requests
GROUP BY borough
ORDER BY requests DESC;
------
/* Task 5: Trend over time
Finding:Only 10 days of data, so there’s no monthly trend. 
The daily peak was 26 Oct (12,500).*/
SELECT TO_CHAR(created_date, 'YYYY-MM') AS year_month, COUNT(*) AS requests
FROM service_requests
GROUP BY year_month
ORDER BY year_month;

SELECT DATE(created_date) AS day, COUNT(*) AS requests
FROM service_requests
GROUP BY day
ORDER BY day;
------
/*Task 6a: By weekday, ISODOW sorts Monday→Sunday instead of alphabetically. 
Findings: Friday is the busiest day (about 23,600). 
Sunday is the quietest (10,478).*/
SELECT weekday, COUNT(*) AS requests
FROM service_requests
GROUP BY weekday, EXTRACT(ISODOW FROM created_date)
ORDER BY EXTRACT(ISODOW FROM created_date);
------
/* Task 6b: Requests by hour 
Findings:Demand peaks late morning (10–12 h, about 6,000 per hour).
*/
SELECT hour, COUNT(*) AS requests
FROM service_requests
GROUP BY hour
ORDER BY hour;
------
/*Status and resolution time-
Task 7: Status distribution
Findings: 70.8% Closed, 16.9% Open, 
12.0% In Progress.
*/
SELECT status, COUNT(*) AS requests
FROM service_requests
GROUP BY status
ORDER BY requests DESC;
------
/* Task 8: Descriptive statistics of resolution hours
Findings:Median 2.6 h vs mean 18.2 h; Q1 0.75 h, Q3 19.2 h. 
A few long cases pull the mean up.
*/
SELECT COUNT(resolution_hours) AS n,
       ROUND(MIN(resolution_hours)::numeric, 2) AS min,
       ROUND(MAX(resolution_hours)::numeric, 2) AS max,
       ROUND(AVG(resolution_hours)::numeric, 2) AS mean,
       ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS q1,
       ROUND(PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS median,
       ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS q3,
       ROUND(STDDEV(resolution_hours)::numeric, 2) AS std_dev
FROM service_requests
WHERE resolution_hours IS NOT NULL;
------
/* Task 9: Median resolution by complaint type
HAVING COUNT(*) >= 50 skips tiny categories whose median isn’t reliable.
Findings:Housing complaints are slowest: WATER LEAK has a median of 95.9 h and 
UNSANITARY CONDITION 91.0 h.
*/
SELECT complaint_type, COUNT(*) AS n,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_hours
FROM service_requests
WHERE resolution_hours IS NOT NULL
GROUP BY complaint_type
HAVING COUNT(*) >= 50
ORDER BY median_hours DESC
LIMIT 15;
------
/*Task 10: Median resolution by agency
Findings: NYPD closes fastest (median 1.3 h). HPD is slow (55.3 h). DOB shows 0 h, which suggests same-time 
administrative closures, so treat it with caution.
*/
SELECT agency, COUNT(*) AS n,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_hours
FROM service_requests
WHERE resolution_hours IS NOT NULL
GROUP BY agency
ORDER BY median_hours DESC;
------
/* Task 11a: How many outliers?
Findings:Findings: 10,916 outliers vs 62,149 normal closed requests.
*/
SELECT is_outlier, COUNT(*) AS requests
FROM service_requests
WHERE resolution_hours IS NOT NULL
GROUP BY is_outlier;
------
/* Task 11b: Which complaint types are outliers? 
Findings:10,916 of 73,065 closed requests (14.9%) are IQR outliers, 
led by HEAT/HOT WATER (3,869).
*/
SELECT complaint_type, COUNT(*) AS outliers
FROM service_requests
WHERE is_outlier = TRUE
GROUP BY complaint_type
ORDER BY outliers DESC
LIMIT 10;
------
/*Task 12: Skewness.
Findings:Pearson skewness is 1.44, 
so the data is right-skewed
*/
SELECT ROUND((3 * (AVG(resolution_hours)
       - PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_hours))
       / STDDEV(resolution_hours))::numeric, 2) AS pearson_skew
FROM service_requests
WHERE resolution_hours IS NOT NULL;
------
/*Location and closure, Rounding to 2 decimals groups requests into small 
grid squares of about 1 km. The top squares are the hotspots.
Task 13: Geographic hotspots
Findings:The top hotspot is the grid square near lat- 40.72, lon−73.98 
(Lower East Side, Manhattan), with 901 requests.
*/
SELECT ROUND(latitude::numeric, 2) AS lat, ROUND(longitude::numeric, 2) AS lon,
       COUNT(*) AS requests
FROM service_requests
WHERE latitude IS NOT NULL
GROUP BY lat, lon
ORDER BY requests DESC
LIMIT 10;
------
/*Task 14: Closure rate by borough
Findings:Queens has the highest closure rate (77.2%) and the Bronx the lowest (69.2%) 
among named boroughs.
*/
SELECT borough, COUNT(*) AS requests,
       ROUND(100.0 * AVG(is_closed::int), 1) AS closure_pct
FROM service_requests
GROUP BY borough
ORDER BY closure_pct DESC;
------
/*Task 15: High volume AND slow
Findings: High-volume and slow: housing issues (WATER LEAK, UNSANITARY CONDITION, 
APPLIANCE, DOOR/WINDOW).
*/
WITH s AS (
  SELECT complaint_type, COUNT(*) AS requests,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_hours) AS median_hours
  FROM service_requests
  GROUP BY complaint_type
)
SELECT complaint_type, requests, ROUND(median_hours::numeric, 1) AS median_hours
FROM s
WHERE requests >= (SELECT AVG(requests) FROM s)
  AND median_hours > (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_hours)
                      FROM service_requests)
ORDER BY median_hours DESC;




