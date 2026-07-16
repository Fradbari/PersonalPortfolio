// frontend/src/App.tsx
import { Route, Routes } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { Accounts } from './pages/Accounts'
import { Backup } from './pages/Backup'
import { CategoriesPending } from './pages/CategoriesPending'
import { Dashboard } from './pages/Dashboard'
import { Import } from './pages/Import'
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
          <Route path="/backup" element={<Backup />} />
        </Routes>
      </main>
    </div>
  )
}
