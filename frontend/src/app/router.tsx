import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { AppLayout } from '@/app/layout'
import { DashboardPage } from '@/pages/Dashboard'
import { RunPipelinePage } from '@/pages/RunPipeline'
import { ActiveRunsPage } from '@/pages/ActiveRuns'
import { RunHistoryPage } from '@/pages/RunHistory'
import { RunDetailPage } from '@/pages/RunDetail'
import { SettingsPage } from '@/pages/Settings'
import { DiagnosticsPage } from '@/pages/Diagnostics'
import { ValidationPage } from '@/pages/Validation'
import { AddReportPage } from '@/pages/AddReport'
import { ReportRegistryPage } from '@/pages/ReportRegistry'
import { OutputsPage } from '@/pages/Outputs'
import { LogsPage } from '@/pages/Logs'
import { CogsPage, PincodePage } from '@/pages/CogsPincode'
import { ConfigOverviewPage } from '@/pages/config/ConfigOverview'
import { ConfigClientsPage } from '@/pages/config/ConfigClients'
import { ConfigGeographiesPage } from '@/pages/config/ConfigGeographies'
import {
  ConfigReportPackagePage,
  ConfigReportsPage,
} from '@/pages/config/ConfigReports'
import { ConfigStagesPage } from '@/pages/config/ConfigStages'
import { ConfigSequencesPage } from '@/pages/config/ConfigSequences'
import { ConfigEnvironmentPage } from '@/pages/config/ConfigEnvironment'
import { ConfigFilesPage } from '@/pages/config/ConfigFiles'
import { ConfigHistoryPage } from '@/pages/config/ConfigHistory'

function RunDetailRoute() {
  const { runId } = useParams()
  if (!runId) return <Navigate to="/pipeline/history" replace />
  return <RunDetailPage runId={runId} />
}

export function AppRouter() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="pipeline/run" element={<RunPipelinePage />} />
        <Route path="pipeline/active" element={<ActiveRunsPage />} />
        <Route path="pipeline/history" element={<RunHistoryPage />} />
        <Route path="pipeline/runs/:runId" element={<RunDetailRoute />} />
        <Route path="pipeline/sequences" element={<ConfigSequencesPage />} />

        <Route path="config" element={<ConfigOverviewPage />} />
        <Route path="config/clients" element={<ConfigClientsPage />} />
        <Route path="config/geographies" element={<ConfigGeographiesPage />} />
        <Route path="config/reports" element={<ConfigReportsPage />} />
        <Route path="config/reports/:packageName" element={<ConfigReportPackagePage />} />
        <Route path="config/stages" element={<ConfigStagesPage />} />
        <Route path="config/sequences" element={<Navigate to="/pipeline/sequences" replace />} />
        <Route path="config/environment" element={<ConfigEnvironmentPage />} />
        <Route path="config/files" element={<ConfigFilesPage />} />
        <Route path="config/history" element={<ConfigHistoryPage />} />

        <Route path="reports/*" element={<Navigate to="/config/reports" replace />} />
        <Route path="developer/add-report" element={<AddReportPage />} />
        <Route path="developer/registry" element={<ReportRegistryPage />} />
        <Route path="developer/validation" element={<ValidationPage />} />
        <Route path="developer/diagnostics" element={<DiagnosticsPage />} />
        <Route path="data/outputs" element={<OutputsPage />} />
        <Route path="data/logs" element={<LogsPage />} />
        <Route path="data/cogs" element={<CogsPage />} />
        <Route path="data/pincode" element={<PincodePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
