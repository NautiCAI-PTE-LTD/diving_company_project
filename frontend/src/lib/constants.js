// Class names mirror the trained species bundle (sync via GET /api/config when loaded).
// Legacy 5-class ids kept for backward compatibility.

export const HULL_REGIONS = [
  { id: 'Bow',                 displayLabel: 'Bow',                 icon: 'Anchor'      },
  { id: 'Verticle_Slide',      displayLabel: 'Vertical Side (Hull)',icon: 'AlignVerticalJustifyCenter' },
  { id: 'Flat_bottom',         displayLabel: 'Flat Bottom',         icon: 'Square'      },
  { id: 'Bilege_keels',        displayLabel: 'Bilge Keels',         icon: 'Waves'       },
  { id: 'Sea_chest',           displayLabel: 'Sea Chest Gratings',  icon: 'Grid3x3'     },
  { id: 'stren',               displayLabel: 'Stern Frame',         icon: 'CornerDownRight' },
  { id: 'Rope',                displayLabel: 'Rope Guard',          icon: 'Spline'      },
  { id: 'Propeller',           displayLabel: 'Propeller',           icon: 'Fan'         },
  { id: 'Radder',              displayLabel: 'Rudder',              icon: 'Compass'     },
  { id: 'Cathodic_Protection', displayLabel: 'Cathodic Protection / Anodes', icon: 'BatteryCharging' },
  { id: 'EGCS',                displayLabel: 'EGCS Outlets',        icon: 'Wind'        },
]

export const SPECIES = [
  { id: 'clean_paint', displayLabel: 'Clean Paint', color: '#10b981' },
  { id: 'slime',       displayLabel: 'Slime',       color: '#fed7aa' },
  { id: 'algae',       displayLabel: 'Algae',       color: '#86efac' },
  { id: 'grass',       displayLabel: 'Grass',       color: '#bbf7d0' },
  { id: 'macroalgae',  displayLabel: 'Grass / Algae', color: '#86efac' },
  { id: 'barnacles',   displayLabel: 'Barnacles',   color: '#f59e0b' },
  { id: 'mussels',     displayLabel: 'Mussels',     color: '#ef4444' },
  { id: 'tubeworms',   displayLabel: 'Tube worms',  color: '#a78bfa' },
  { id: 'goosenecks',  displayLabel: 'Goosenecks',  color: '#d97706' },
  { id: 'calcareous',  displayLabel: 'Calcareous',  color: '#78716c' },
  { id: 'mixed_fouling', displayLabel: 'Mixed',     color: '#6b7280' },
  { id: 'vessel_cover', displayLabel: 'Vessel cover', color: '#94a3b8' },
]

export const STAGES = [
  { id: 'before', displayLabel: 'Before Cleaning', color: '#f97316' },
  { id: 'after',  displayLabel: 'After Cleaning',  color: '#22d3ee' },
  { id: 'not_hull', displayLabel: 'Cover / Not hull', color: '#94a3b8' },
]

export const ROUGHNESS_SCALE = ['A', 'B', 'C', 'D', 'E', 'F']

export const SEVERITY = [
  { id: 'A', label: 'Light',    color: '#10b981' },
  { id: 'B', label: 'Moderate', color: '#f59e0b' },
  { id: 'C', label: 'Heavy',    color: '#ef4444' },
  { id: 'D', label: 'Clean',    color: '#22d3ee' },
]

export const VESSEL_TYPES = ['Cargo', 'Tanker', 'Bulk Carrier', 'Container', 'RoRo', 'Passenger', 'OSV', 'Other']
export const VESSEL_CLASSES = ['BV', 'DNV', 'LR', 'ABS', 'NK', 'CCS', 'KR', 'RINA', 'IRS', 'Other']
