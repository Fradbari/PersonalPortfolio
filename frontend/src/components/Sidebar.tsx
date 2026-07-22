// frontend/src/components/Sidebar.tsx
import { NavLink } from 'react-router-dom'

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/transazioni', label: 'Transazioni' },
  { to: '/import', label: 'Import' },
  { to: '/categorie-pending', label: 'Categorie pending' },
  { to: '/conti', label: 'Conti' },
  { to: '/backup-restore', label: 'Backup' },
  { to: '/assistente-ai', label: 'Assistente AI' },
  { to: '/impostazioni', label: 'Impostazioni' },
]

export function Sidebar() {
  return (
    <nav className="w-56 shrink-0 border-r bg-card p-4">
      <h1 className="mb-6 text-lg font-semibold">Personal Portfolio</h1>
      <ul className="space-y-1">
        {links.map((link) => (
          <li key={link.to}>
            <NavLink
              to={link.to}
              end={link.to === '/'}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm ${
                  isActive ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'
                }`
              }
            >
              {link.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
