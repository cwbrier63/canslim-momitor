"""
CANSLIM Monitor - GUI Package
PyQt6-based graphical user interface components.

Note: PyQt6 must be installed to use GUI components.
"""

from canslim_monitor.gui.state_config import (
    PositionState,
    STATES,
    StateInfo,
    StateTransition,
    VALID_TRANSITIONS,
    get_valid_transitions,
    get_transition,
    is_valid_transition,
    get_kanban_columns,
    VALID_PATTERNS,
    AD_RATINGS,
    BASE_STAGES,
)


def _check_pyqt6():
    """Check if PyQt6 is available."""
    try:
        import PyQt6
        return True
    except ImportError:
        return False


# Lazy imports for PyQt6-dependent modules
def get_position_card():
    """Import PositionCard (requires PyQt6)."""
    from canslim_monitor.gui.position_card import PositionCard
    return PositionCard


def get_kanban_column():
    """Import KanbanColumn (requires PyQt6)."""
    from canslim_monitor.gui.kanban_column import KanbanColumn, ClosedPositionsPanel
    return KanbanColumn, ClosedPositionsPanel


def get_dialogs():
    """Import dialogs (requires PyQt6)."""
    from canslim_monitor.gui.transition_dialogs import (
        TransitionDialog, AddPositionDialog, ExitToReentryWatchDialog
    )
    return TransitionDialog, AddPositionDialog, ExitToReentryWatchDialog


def get_main_window():
    """Import main window (requires PyQt6)."""
    from canslim_monitor.gui.kanban_window import (
        MarketRegimeBanner,
        ServiceControlPanel,
        KanbanMainWindow,
    )
    return MarketRegimeBanner, ServiceControlPanel, KanbanMainWindow


def launch_gui(db_path: str):
    """Launch the Kanban GUI application."""
    if not _check_pyqt6():
        raise ImportError(
            "PyQt6 is required for the GUI. Install with: pip install PyQt6"
        )
    from canslim_monitor.gui.kanban_window import launch_gui as _launch
    _launch(db_path)


__all__ = [
    # State config (always available)
    'PositionState',
    'STATES',
    'StateInfo',
    'StateTransition',
    'VALID_TRANSITIONS',
    'get_valid_transitions',
    'get_transition',
    'is_valid_transition',
    'get_kanban_columns',
    'VALID_PATTERNS',
    'AD_RATINGS',
    'BASE_STAGES',
    # Lazy imports
    'get_position_card',
    'get_kanban_column',
    'get_dialogs',
    'get_main_window',
    'launch_gui',
]
