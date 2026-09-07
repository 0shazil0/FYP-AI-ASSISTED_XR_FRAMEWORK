// Assets/Scripts/Copilot/CopilotStateMachine.cs
// ==============================================
// Finite state machine for the UI Copilot session.
// Manages the lifecycle from Idle → Listening → Querying → Guiding → Done.
// Other components call SetState() or read the current state to drive UI/TTS.
//
// STATES:
//   Idle         → No session. Show mic button + input field.
//   Listening    → Mic open. Awaiting user voice input.
//   Querying     → Request sent to backend. "Asking AI..." spinner.
//   Guiding      → Steps received. AR overlay visible. Step-by-step mode.
//   Verifying    → step_done sent. Awaiting step_verification response.
//   Done         → All steps complete. Show summary + reset option.
//   Error        → Backend or network error. Show message + retry button.
//
// USAGE:
//   stateMachine.SetState(CopilotState.Listening);
//   stateMachine.OnStateChanged += (prev, next) => { ... };

using System;
using UnityEngine;

namespace NeuroGuideXR.Copilot
{
    /// <summary>All possible states of a UI Copilot session.</summary>
    public enum CopilotState
    {
        /// <summary>No active session. Idle screen shown.</summary>
        Idle,

        /// <summary>Microphone is open and awaiting speech.</summary>
        Listening,

        /// <summary>Query sent to backend. Waiting for AI response.</summary>
        Querying,

        /// <summary>Steps received. AR overlay is active and guiding the user.</summary>
        Guiding,

        /// <summary>step_done sent. Waiting for step_verification from backend.</summary>
        Verifying,

        /// <summary>All steps completed successfully.</summary>
        Done,

        /// <summary>An error occurred. Error message is shown.</summary>
        Error,
    }

    /// <summary>
    /// Manages state transitions for the UI Copilot mode.
    /// Other components subscribe to OnStateChanged to react to transitions.
    /// </summary>
    public sealed class CopilotStateMachine : MonoBehaviour
    {
        // ----------------------------------------------------------------
        // Events
        // ----------------------------------------------------------------

        /// <summary>
        /// Fired whenever the state changes.
        /// Args: (previousState, newState)
        /// </summary>
        public event Action<CopilotState, CopilotState> OnStateChanged;

        /// <summary>
        /// Fired when an error state is entered, carrying the error message.
        /// </summary>
        public event Action<string> OnErrorEntered;

        // ----------------------------------------------------------------
        // State
        // ----------------------------------------------------------------
        private CopilotState _state = CopilotState.Idle;

        // Track step progress for state context
        private int _totalSteps   = 0;
        private int _currentStep  = 0;
        private string _lastError = "";

        // ----------------------------------------------------------------
        // Properties
        // ----------------------------------------------------------------
        public CopilotState CurrentState  => _state;
        public int          TotalSteps    => _totalSteps;
        public int          CurrentStep   => _currentStep;
        public string       LastError     => _lastError;
        public bool         IsIdle        => _state == CopilotState.Idle;
        public bool         IsGuiding     => _state == CopilotState.Guiding;
        public bool         IsListening   => _state == CopilotState.Listening;
        public bool         IsBusy        => _state == CopilotState.Querying
                                          || _state == CopilotState.Verifying;

        // ----------------------------------------------------------------
        // Public Transition API
        // ----------------------------------------------------------------

        /// <summary>
        /// Transition to a new state. Logs the transition and fires OnStateChanged.
        /// No-op if already in the target state.
        /// </summary>
        public void SetState(CopilotState next)
        {
            if (_state == next) return;

            CopilotState prev = _state;
            _state = next;

            Debug.Log($"[CopilotSM] {prev} → {next}");
            OnStateChanged?.Invoke(prev, next);
        }

        /// <summary>
        /// Shortcut: transition to Error and emit error message.
        /// </summary>
        public void SetError(string message)
        {
            _lastError = message ?? "Unknown error.";
            SetState(CopilotState.Error);
            OnErrorEntered?.Invoke(_lastError);
        }

        /// <summary>
        /// Called when copilot_steps arrives. Updates step counters + transitions to Guiding.
        /// </summary>
        public void OnStepsReceived(int total)
        {
            _totalSteps  = total;
            _currentStep = 0;
            SetState(CopilotState.Guiding);
        }

        /// <summary>
        /// Called when the user taps "Done" on a step. Transitions to Verifying.
        /// </summary>
        public void OnStepDoneTapped(int stepIndex)
        {
            _currentStep = stepIndex;
            SetState(CopilotState.Verifying);
        }

        /// <summary>
        /// Called when step_verification arrives from the backend.
        /// If passed and more steps remain → back to Guiding.
        /// If passed and last step → Done.
        /// If not passed → back to Guiding (user must retry the step).
        /// </summary>
        public void OnVerificationResult(int stepIndex, bool passed)
        {
            if (passed)
            {
                bool isLast = stepIndex >= _totalSteps - 1;
                SetState(isLast ? CopilotState.Done : CopilotState.Guiding);
            }
            else
            {
                // Failed verification: stay on current step
                SetState(CopilotState.Guiding);
            }
        }

        /// <summary>Reset everything back to Idle (user taps Reset or finishes session).</summary>
        public void Reset()
        {
            _totalSteps  = 0;
            _currentStep = 0;
            _lastError   = "";
            SetState(CopilotState.Idle);
        }

        // ----------------------------------------------------------------
        // Guard helpers
        // ----------------------------------------------------------------

        /// <summary>Returns true if transitioning to the given state is valid from current state.</summary>
        public bool CanTransitionTo(CopilotState next)
        {
            return next switch
            {
                CopilotState.Idle       => true,                       // can always reset
                CopilotState.Listening  => _state == CopilotState.Idle || _state == CopilotState.Error,
                CopilotState.Querying   => _state == CopilotState.Listening || _state == CopilotState.Idle,
                CopilotState.Guiding    => _state == CopilotState.Querying || _state == CopilotState.Verifying,
                CopilotState.Verifying  => _state == CopilotState.Guiding,
                CopilotState.Done       => _state == CopilotState.Verifying || _state == CopilotState.Guiding,
                CopilotState.Error      => true,                       // any state can error
                _                       => false,
            };
        }
    }
}
