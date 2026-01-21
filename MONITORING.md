# Monitoring Strategy: Power BI vs. Microsoft Graph

## Executive Summary

Recommendation: Power BI for data analytics + Azure Monitor for Function App health

| Aspect | Power BI | Microsoft Graph | Winner |
| --- | --- | --- | --- |
| Setup Complexity | 15 minutes | 2-3 hours | Power BI ✅ |
| Ongoing Maintenance | Minimal | High | Power BI ✅ |
| Cost | $10-15/user/month | Included (dev overhead) | Power BI ✅ |
| Visualization Quality | Excellent time-series, heatmaps | N/A (monitoring only) | Power BI ✅ |
| Domain Fit | Perfect (training analytics) | Sub-optimal (file monitoring) | Power BI ✅ |
| Integration | Direct Table Storage | OneDrive file monitoring | Power BI ✅ |
| Learning Curve | Power BI UI (easy) | C#/Python SDK (moderate) | Power BI ✅ |

## Why Power BI

### 1. **Solves the Right Problem**

- **Goal**: Monitor and analyze training data in Azure Table Storage
- **Power BI**: Direct connectors to Table Storage, real-time dashboards, built-in time-series visualizations
- **Graph**: Designed for OneDrive file monitoring, not data analytics

### 2. Simplicity & Speed

```text
Power BI approach:
- Connect to Storage Account (20 sec)
- Select tables (10 sec)
- Build dashboard (5 min)
= 15 minutes total

Microsoft Graph approach:
- Set up app registration (10 min)
- Develop Python/C# client (45 min)
- Handle auth tokens (20 min)
- Deploy new function (15 min)
= 1-2 hours + ongoing maintenance
```

### 3. **Cost Efficiency**

- **Power BI**: $10-15/user/month (only athletes using it)
- **Microsoft Graph**: No direct cost, but development and maintenance overhead
- **Azure Monitor**: ~$5-10/month for diagnostics (handles Function App health)

### 4. **Perfect for This Domain**

Training data is inherently time-series and multi-dimensional:

- Weekly volume trends
- Zone distribution analysis
- Fatigue patterns
- Intensity vs. recovery
- Power/heart-rate trends

Power BI excels at these visualizations. Graph is for file synchronization.

### 5. **Alignment with Architecture**

This project separates concerns:

- **Ingestion**: OneDrive → Power Automate → Azure Functions
- **Storage**: Azure Table Storage
- **Analytics**: Power BI (this is the read layer)
- **Integration**: ChatGPT via Semantic Layer API

Power BI fits naturally as the analytics layer. Graph would duplicate Power Automate's file-monitoring role.

---

## Implementation: Power BI Dashboard

### Prerequisites

- Azure Storage Account with tables: `Workouts`, `WeeklyRollups`, `IngestionState`
- Power BI Desktop (free) or Power BI Pro subscription ($10/month)
- Azure Storage account credentials

### Step 1: Connect Power BI to Azure Table Storage

**In Power BI Desktop:**

1. **Get Data** → **Azure** → **Azure Table Storage**
2. **Enter Storage Account Name**: `<your-storage-account>`
3. **Select tables**: `Workouts`, `WeeklyRollups`, `IngestionState`
4. **Load** data

Alternative (Web Interface):

```text
Power BI Online (powerbi.microsoft.com)
→ Create new dashboard
→ Get Data
→ Azure Table Storage
→ Configure connection
```

### Step 2: Create Key Visualizations

#### Dashboard 1: Training Overview

- **Line chart**: Volume over time (duration_sec by date)
- **Stacked column**: Weekly zone distribution (z1-z5 minutes)
- **Card**: Total workouts this month, average intensity
- **Map**: Sport distribution (bar chart of sport types)

#### Dashboard 2: Physiometrics Trends

- **Line chart**: Weekly average power (pwr_avg_watts)
- **Line chart**: Weekly average heart rate (hr_avg_bpm)
- **Scatter**: Power vs. HR by date (detect decoupling)
- **Card**: Current FTP, LTHR, VO2Max

#### Dashboard 3: Data Quality

- **Line chart**: Ingestion success rate (IngestionState)
- **Table**: Recent processing errors
- **Card**: Last update timestamp
- **Gauge**: Data completeness (missing HR % across workouts)

#### Dashboard 4: Load Management

- **Line chart**: Cumulative TSS (training_stress_score) by week
- **Column chart**: IF distribution (intensity_factor by workout)
- **Heatmap**: Workouts by time of day + zone (reveals patterns)

### Step 3: Set Up Refresh Schedule

**Power BI Pro:**

```text
Settings → Scheduled Refresh
→ Refresh every 24 hours at 2 AM (off-peak)
```

**Power BI Desktop:**

```text
Transform Data → Query Settings
→ Folds/performance optimized queries
```

### Step 4: Create Alerts

```text
Power BI Online (Pro only)
→ Pin visualization
→ Set alert rule:
  "Alert when IngestionState has errors > 2 in last 24h"
  "Alert when workout count drops below expected"
```

---

## Implementation: Azure Monitor for Function App Health

For monitoring the **Function App itself** (not data):

### Step 1: Enable Application Insights

```bash
# Create Application Insights resource
az monitor app-insights component create \
  --app fitprocessor-insights \
  --location $LOCATION \
  --resource-group $RESOURCE_GROUP

# Link to Function App
az functionapp config appsettings set \
  --name $FUNCTION_APP \
  --resource-group $RESOURCE_GROUP \
  --settings "APPINSIGHTS_INSTRUMENTATION_KEY=<key>"
```

### Step 2: Set Up Alerts

```bash
# Alert on Function App failures
az monitor metrics alert create \
  --name "FitProcessor Errors" \
  --resource-group $RESOURCE_GROUP \
  --scopes "/subscriptions/{subscriptionId}/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_APP" \
  --condition "avg Exceptions > 5" \
  --window-size 1h \
  --evaluation-frequency 15m \
  --action "log" "email"
```

### Step 3: View Diagnostics

```bash
# Tail live logs
az functionapp log tail \
  --name $FUNCTION_APP \
  --resource-group $RESOURCE_GROUP \
  --provider Microsoft.Web/sites/config/logs

# View performance insights
# Azure Portal → Function App → Application Insights → Performance
```

---

## Why NOT Microsoft Graph Monitoring

### Problems with Graph-based OneDrive Monitoring

1. **Redundant with Power Automate**
   - You already monitor OneDrive with Power Automate
   - Graph would duplicate this work
   - Adds maintenance without benefit

2. **Higher Complexity**

   ```python
   # Graph approach requires:
   - OAuth token management
   - Polling logic (no webhooks for file changes)
   - Error retry logic
   - Dependency on msgraph-sdk
   - New timer function to create/deploy
   - Testing/debugging cycle
   ```

3. **Wrong Level of Abstraction**
   - Designed for: File synchronization, OneDrive administration
   - Needed for: Training data analytics and visualization
   - Mismatch creates unnecessary coupling

4. **Operational Overhead**
   - Requires deployment of new function
   - Adds to monthly cost (compute)
   - Extra logging/debugging surface
   - Not suitable for non-engineers

5. **No Value Add**
   - Power Automate already handles "new file detected"
   - Graph would only add "process at interval" (worse UX)
   - No analytics capability

---

## Architecture After Implementation

```text
OneDrive (/Apps/HealthFit/)
    ↓
Power Automate Flow
    ↓
Azure Function (process_fit endpoint)
    ↓
Azure Table Storage
    ├── Workouts
    ├── WeeklyRollups
    └── IngestionState
    ↓
┌─────────────────────────────────────┐
│ Semantic Layer API                  │
│ (ChatGPT/LLM Integration)           │
└─────────────────────────────────────┘
    ↓                              ↓
ChatGPT UI                    Power BI Dashboard
(Real-time context)           (Historical trends)
```

**Key Separation:**

- **Ingestion**: Power Automate + Azure Functions
- **Storage**: Azure Table Storage
- **Querying**: Semantic Layer API (real-time for ChatGPT)
- **Analytics**: Power BI (dashboards, trends, alerts)
- **Health**: Azure Monitor + Application Insights

---

## Quick Start Checklist

- [ ] **Data Ready**: Verify `Workouts`, `WeeklyRollups` tables have data
- [ ] **Power BI Access**: Get subscription (free or Pro)
- [ ] **Create Connection**: Connect to Azure Storage Account
- [ ] **Build Dashboard**: Follow Step 2 visualizations
- [ ] **Set Refresh**: Auto-refresh every 24 hours
- [ ] **Share**: Invite athletes to Power BI workspace
- [ ] **Monitor Alerts**: Set up email/Teams notifications for anomalies
- [ ] **Document**: Share dashboard link in team channel

---

## Next Steps

1. **This sprint**: Implement Power BI dashboard (4-8 hours including learning)
2. **Optional**: Set up Application Insights for Function App errors
3. **Remove**: Graph monitoring reference from DEPLOYMENT.md
4. **Document**: Share Power BI Quick Start with team

---

## Dashboard User Guide (For Athletes)

### What is Power BI?

A dashboard tool that visualizes your training data in real-time.

### What You'll See

- **Weekly Volume**: How many hours you trained this week
- **Zone Distribution**: How much time in easy (Z1-2) vs. hard (Z4-5) zones
- **Trends**: Power and heart rate over time to spot fitness gains
- **Alerts**: Notifications if something looks off (missed data, unusual pattern)

### Setup (15 minutes)

#### Step 1: Get Power BI Access

1. Ask your administrator for Power BI access
2. Navigate to [powerbi.microsoft.com](https://powerbi.microsoft.com)
3. Sign in with your work account

#### Step 2: Open the Dashboard

- Look for **"Health Assistant - Training Analytics"** workspace
- Click to open
- You'll see 4 tabs at the top:
  - **Training Overview**
  - **Physiometrics Trends**
  - **Data Quality**
  - **Load Management**

#### Step 3: Explore

- **Hover** over charts to see numbers
- **Click** on a workout sport to filter other charts
- **Use date filters** at the top to zoom in/out

### Dashboard Guide

#### Tab 1: Training Overview

| Card | What It Means |
| --- | --- |
| Total Workouts | How many sessions logged |
| Total Duration | Total training hours this month |
| Avg Intensity | 0-100 scale; higher = harder |
| Chart (Volume) | Line going up = getting more volume |
| Chart (Zones) | Stack shows Z1 (easy, blue) through Z5 (hard, red) |

**What to look for:**

- ✅ Volume increasing week-by-week (steady progression)
- ⚠️ Sudden drop (under-training or injury?)
- ⚠️ All red zone (over-training, no recovery)

#### Tab 2: Physiometrics Trends

| Chart | What It Means |
| --- | --- |
| Power Trend | Your average watts per workout (higher = stronger) |
| HR Trend | Your average heart rate per workout (lower = fitter) |
| Power vs. HR Scatter | Each dot = one workout; points drifting right = getting stronger |
| Metrics Cards | Current FTP (functional threshold power), LTHR (lactate threshold HR) |

**What to look for:**

- ✅ Power going up (getting stronger)
- ✅ HR going down at same power (getting fitter - aerobic adaptation)
- ⚠️ Power steady but HR high (fatigue, need recovery)
- ⚠️ HR and power both down (something's wrong, check data)

#### Tab 3: Data Quality

| Element | What It Means |
| --- | --- |
| Success Rate % | Percentage of workouts processed successfully |
| Last Update | When data was last refreshed |
| Recent Errors | Any processing problems (usually empty = good) |

**What to do:**

- ✅ > 98% = Great, data is reliable
- ⚠️ < 95% = Check for corrupt files or sync issues
- 🔴 Red error = Contact support with timestamp

#### Tab 4: Load Management

| Chart | What It Means |
| --- | --- |
| TSS (Training Stress) | Cumulative training load over time (higher = more stressed) |
| IF Distribution | Each bar = intensity factor of that workout (0-100%) |
| Time of Day Heatmap | When you train most (dark = lots, light = few) |

**What to look for:**

- ✅ TSS 100-200/week (moderate load)
- ⚠️ TSS > 250/week (high load - ensure recovery)
- ⚠️ TSS < 50/week (low volume - consistency needed)
- ✅ Mix of different times = flexible schedule

### Common Questions

**Q: Why is my data from yesterday missing?**

A: Power BI refreshes every 24 hours (usually 2 AM). Check back in the morning.

**Q: Can I export a chart?**

A: Yes! Click **...** (three dots) on any chart → **Export data** or **Export image**

**Q: How do I share this with a coach?**

A: Click **Share** button (top right) → Enter coach email → They get dashboard link

**Q: Why is a workout missing?**

A:

1. Check **Data Quality** tab for errors
2. Verify file uploaded to OneDrive folder
3. Check Power Automate flow is enabled
4. Contact support if persists

**Q: Can I filter by date range?**

A: Yes! Use the date slicers at top of dashboard. Click date → select range

**Q: What if a chart looks wrong?**

A:

1. Refresh dashboard (Ctrl+R or ⌘+R)
2. Check if a filter is applied (colored button = active)
3. Clear filters by clicking the **X** on date/sport filter
4. Report issue with specific date if problem persists

### Tips for Athletes

**Best Practices:**

1. **Check weekly** - Pick Sunday evening to review the week
2. **Note changes** - If a metric changes significantly, check your training plan
3. **Use for planning** - Low fatigue? Good time for intensity. High TSS? Plan recovery
4. **Share trends** - Show coach the power/HR improvements

**Integration with ChatGPT:**

- Power BI shows **historical trends**
- ChatGPT gets **real-time context** for daily decisions
- Together: Long-term vision + daily guidance

**Training Insights to Look For:**

| Observation | Insight |
| --- | --- |
| Power up 5-10 W/month | FTP improving, try harder intervals |
| HR down 3-5 bpm at same power | Aerobic base improving, fitness is building |
| All Z1-2 (low zone) | Need some intensity work to maintain edge |
| Lots of Z4-5 (high zone) | Good! But ensure 80/20 ratio (80% easy, 20% hard) |
| TSS climbing | Recovery is important - plan rest days |
| Morning HR up 5 bpm | Might be fatigued - dial back intensity |

### Need Help?

**Getting Started:**

- Read [DEPLOYMENT.md](./DEPLOYMENT.md) for technical setup
- Ask administrator for Power BI workspace access

**Troubleshooting:**

1. Can't see data? → Check if tables are populated in Azure
2. Dashboard won't refresh? → Verify storage account connection
3. Chart looks odd? → Clear filters and refresh

**Reporting Issues:**

Include in your report:

- What you were trying to do
- What happened instead
- Screenshot if possible
- Approximate date/time of issue

### Advanced: Custom Queries

If you want to create your own queries:

1. Click **Edit** (top left)
2. Click **Transform Data**
3. You can now filter/sort/group the data
4. Create new visualizations
5. Save and share

**Common queries:**

- Show only cycling workouts
- Average watts for each sport
- Workouts over 2 hours
- Last 7 days only

---

- [Power BI + Azure Storage Integration](https://learn.microsoft.com/en-us/power-bi/connect-data/storage-gateway-personal-gateway)
- [Power BI Time Series Analysis](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-decomposition-tree)
- [Azure Monitor for Functions](https://learn.microsoft.com/en-us/azure/azure-functions/functions-monitoring)
- [Application Insights Best Practices](https://learn.microsoft.com/en-us/azure/azure-monitor/app/best-practices)
