import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { AppLayout } from '@/app/layout'
import { DashboardPage } from '@/pages/Dashboard'
import { RunPipelinePage } from '@/pages/RunPipeline'
import { ActiveRunsPage } from '@/pages/ActiveRuns'
import { RunHistoryPage } from '@/pages/RunHistory'
import { RunDetailPage } from '@/pages/RunDetail'
import { ReportsPage } from '@/pages/Reports'
import { ClientsPage } from '@/pages/Clients'
import { GeographiesPage } from '@/pages/Geographies'
import { SequencesPage } from '@/pages/Sequences'
import { StagesPage } from '@/pages/Stages'
import { SettingsPage } from '@/pages/Settings'
import { EnvironmentPage } from '@/pages/Environment'
import { DiagnosticsPage } from '@/pages/Diagnostics'
import { ValidationPage } from '@/pages/Validation'
import { AddReportPage } from '@/pages/AddReport'
import { ReportRegistryPage } from '@/pages/ReportRegistry'
import { OutputsPage } from '@/pages/Outputs'
import { LogsPage } from '@/pages/Logs'
import { CogsPage, PincodePage } from '@/pages/CogsPincode'

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
        <Route path="pipeline/sequences" element={<SequencesPage />} />
        <Route path="config/clients" element={<ClientsPage />} />
        <Route path="config/geographies" element={<GeographiesPage />} />
        <Route path="config/reports" element={<ReportsPage mode="all" />} />
        <Route path="config/stages" element={<StagesPage />} />
        <Route path="config/environment" element={<EnvironmentPage />} />
        <Route path="reports" element={<ReportsPage mode="all" />} />
        <Route path="reports/standard" element={<ReportsPage mode="standard" />} />
        <Route path="reports/requirement" element={<ReportsPage mode="requirement" />} />
        <Route path="reports/utilities" element={<ReportsPage mode="utilities" />} />
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
