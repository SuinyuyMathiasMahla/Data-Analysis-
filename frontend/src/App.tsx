import { Link, Navigate, Route, Routes } from "react-router-dom";

import AppLayout, { PublicLayout } from "./layouts/AppLayout";
import ProjectLayout from "./layouts/ProjectLayout";
import { Admin, Profile, Settings } from "./pages/Account";
import { Descriptive, Exploratory, PowerPlanner } from "./pages/AnalysisPages";
import { AutomaticAnalysis } from "./pages/AutomaticAnalysis";
import { ChartReview } from "./pages/ChartReview";
import Assistant from "./pages/Assistant";
import VisualizationStudio from "./pages/Charts";
import Dashboard from "./pages/Dashboard";
import { DataCleaning, DataDictionary, DataQuality, DatasetPreview, DatasetUpload } from "./pages/DataPages";
import { Conclusions, Findings, Recommendations } from "./pages/Evidence";
import ProjectOverview from "./pages/ProjectOverview";
import { ClientInfoForm, ProjectForm, ProjectList, ProjectTypeChoice } from "./pages/Projects";
import { ProjectHistory, ReportGenerator } from "./pages/ReportsHistory";
import ProjectCosts from "./pages/ProjectCosts";
import { Hypotheses, ResearchQuestions } from "./pages/ResearchDesign";
import { ForgotPassword, Login, Register, ResetPassword, VerifyEmail } from "./pages/public/Auth";
import Landing from "./pages/public/Landing";

function NotFound() {
  return (
    <main className="page">
      <div className="panel empty">
        <h3>This page does not exist</h3>
        <p>The address may be mistyped, or the page may have moved.</p>
        <Link className="btn primary" to="/dashboard">Go to the dashboard</Link>
      </div>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
      </Route>

      <Route element={<AppLayout />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/projects" element={<ProjectList />} />
        <Route path="/projects/new" element={<ProjectTypeChoice />} />
        <Route path="/projects/new/client" element={<ClientInfoForm />} />
        <Route path="/projects/new/details" element={<ProjectForm />} />
        <Route path="/projects/:projectId/edit" element={<ProjectForm />} />
        <Route path="/power" element={<PowerPlanner />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/projects/:projectId" element={<ProjectLayout />}>
          <Route index element={<ProjectOverview />} />
          <Route path="research-questions" element={<ResearchQuestions />} />
          <Route path="hypotheses" element={<Hypotheses />} />
          <Route path="upload" element={<DatasetUpload />} />
          <Route path="preview" element={<DatasetPreview />} />
          <Route path="quality" element={<DataQuality />} />
          <Route path="cleaning" element={<DataCleaning />} />
          <Route path="dictionary" element={<DataDictionary />} />
          <Route path="explore" element={<Exploratory />} />
          <Route path="descriptive" element={<Descriptive />} />
          <Route path="analysis" element={<AutomaticAnalysis />} />
          <Route path="charts" element={<VisualizationStudio />} />
          <Route path="assistant" element={<Assistant />} />
          <Route path="findings" element={<Findings />} />
          <Route path="conclusions" element={<Conclusions />} />
          <Route path="recommendations" element={<Recommendations />} />
          <Route path="visuals" element={<ChartReview />} />
          <Route path="report" element={<ReportGenerator />} />
          <Route path="costs" element={<ProjectCosts />} />
          <Route path="history" element={<ProjectHistory />} />
          <Route path="*" element={<Navigate to="." replace />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
