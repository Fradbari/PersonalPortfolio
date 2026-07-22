// frontend/src/App.tsx
import { Route, Routes } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { Accounts } from './pages/Accounts'
import { AiAssistant } from './pages/AiAssistant'
import { Backup } from './pages/Backup'
import { CategoriesPending } from './pages/CategoriesPending'
import { Dashboard } from './pages/Dashboard'
import { Import } from './pages/Import'
import { Settings } from './pages/Settings'
import { Transactions } from './pages/Transactions'

export default function App() {
  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/transazioni" element={<Transactions />} />
          <Route path="/import" element={<Import />} />
          <Route path="/categorie-pending" element={<CategoriesPending />} />
          <Route path="/conti" element={<Accounts />} />
          <Route path="/backup-restore" element={<Backup />} />
          <Route path="/assistente-ai" element={<AiAssistant />} />
          <Route path="/impostazioni" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}
