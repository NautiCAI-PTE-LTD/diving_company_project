// Class names taken DIRECTLY from the trained model bundles in /Models.
// Spelling is preserved (Bilege_keels, Radder, Verticle_Slide, stren) because
// the integer label index inside the .pth checkpoint is bound to these strings.
// The displayLabel field is what we render to the user.

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
  { id: 'algae',       displayLabel: 'Algae',       color: '#84cc16' },
  { id: 'macroalgae',  displayLabel: 'Macroalgae',  color: '#22c55e' },
  { id: 'barnacles',   displayLabel: 'Barnacles',   color: '#f59e0b' },
  { id: 'mussels',     displayLabel: 'Mussels',     color: '#ef4444' },
]

// Stage = before / after cleaning (binary head from Before_and_after.h5)
export const STAGES = [
  { id: 'before', displayLabel: 'Before Cleaning', color: '#f97316' },
  { id: 'after',  displayLabel: 'After Cleaning',  color: '#22d3ee' },
]

// Rubert roughness comparator scale used in the report
export const ROUGHNESS_SCALE = ['A', 'B', 'C', 'D', 'E', 'F']

// Severity matches the PDF's "Severity: (A) Light (B) Moderate (C) Heavy (D) Clean"
export const SEVERITY = [
  { id: 'A', label: 'Light',    color: '#10b981' },
  { id: 'B', label: 'Moderate', color: '#f59e0b' },
  { id: 'C', label: 'Heavy',    color: '#ef4444' },
  { id: 'D', label: 'Clean',    color: '#22d3ee' },
]

export const VESSEL_TYPES = ['Cargo', 'Tanker', 'Bulk Carrier', 'Container', 'RoRo', 'Passenger', 'OSV', 'Other']
export const VESSEL_CLASSES = ['BV', 'DNV', 'LR', 'ABS', 'NK', 'CCS', 'KR', 'RINA', 'IRS', 'Other']
