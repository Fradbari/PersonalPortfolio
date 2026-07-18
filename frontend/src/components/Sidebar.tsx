// frontend/src/components/Sidebar.tsx
import { NavLink } from 'react-router-dom'

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/transazioni', label: 'Transazioni' },
  { to: '/import', label: 'Import' },
  { to: '/categorie-pending', label: 'Categorie pending' },
  { to: '/conti', label: 'Conti' },
  { to: '/backup', label: 'Backup' },
  { to: '/assistente-ai', label: 'Assistente AI' },
]

export function Sidebar() {
  return (
    <nav className="w-56 shrink-0 border-r bg-white p-4">
      <h1 className="mb-6 text-lg font-semibold">Personal Portfolio</h1>
      <ul className="space-y-1">
        {links.map((link) => (
          <li key={link.to}>
            <NavLink
              to={link.to}
              end={link.to === '/'}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm ${
                  isActive ? 'bg-gray-900 text-white' : 'text-gray-700 hover:bg-gray-100'
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
