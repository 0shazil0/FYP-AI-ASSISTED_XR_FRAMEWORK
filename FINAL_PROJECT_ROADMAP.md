# NeuroGuide XR Final Project Roadmap

## 1. Executive Synthesis
This roadmap combines:
- [Implementation_plan_2.0.md](Implementation_plan_2.0.md)
- [AR_LIVE_GUIDANCE_PHASE1_PLAN.md](AR_LIVE_GUIDANCE_PHASE1_PLAN.md)

Core decision:
- Keep the working vision LLM snapshot analysis path as the active baseline
- Add fast perception and precision layers incrementally, not as a replacement
- Build a hybrid stack for publishable results: fast detector + triggered deep semantics + structured reasoning + grounded AR overlays

## 2. Current Baseline (What Is Already Working)
- Mobile to backend websocket snapshot flow is stable
- Scene summary and object extraction now return reliably
- Unity can send frames and receive guidance
- Backend already has modular service scaffolding for expanded perception

This is a strong Phase 0 completion point.

## 3. Target Production Architecture (Hybrid)
1. Fast Perception Layer
- YOLO26 ONNX for frequent low-latency detections
- Continuous updates at high frequency

2. Deep Semantic Layer (Triggered)
- Grounding DINO for open-vocabulary detection
- SAM or MobileSAM for segmentation where precision matters
- Optional depth for better world placement

3. Reasoning Layer
- Keep current model analysis path for scene understanding and instruction generation
- Prefer structured scene JSON as reasoning input

4. XR Delivery Layer
- World anchored step card
- Object-linked arrow and highlight cues
- Confidence-aware fallback UI

## 4. Model Strategy You Requested
### Keep current model
- Continue using current snapshot analysis model as baseline scene reasoner
- Use it for instruction synthesis and fallback when detector confidence is low

### Add YOLO26 ONNX in parallel
- Load [backend/yolo26n.onnx](backend/yolo26n.onnx)
- Run YOLO on frequent frames
- Send detections into scene fusion
- Trigger expensive semantic refresh only when needed

### Trigger policy
Run deep semantic calls when:
- Scene change spike
- New or uncertain object appears
- User asks detailed object-level question
- Confidence from fast detector drops

## 5. IMU Integration Plan (Low Latency Motion Tracking)
You can do this in two ways.

### Option A: Unity native device IMU (recommended first)
- Use Unity Input System or platform sensor APIs
- Capture accelerometer + gyroscope + device attitude directly in app
- Include IMU packet with each frame message or as periodic imu message

Pros:
- Lowest integration friction
- Single app deployment
- Synchronized with AR camera lifecycle

### Option B: External Android IMU app to backend
- Use a sensor streaming app sending UDP/WebSocket IMU to backend
- Backend fuses IMU with vision timing

Pros:
- Useful for sensor experiments
- Easy independent calibration testing

Cons:
- Harder time sync with camera stream

### Recommended fusion approach
- Start with complementary filter for short-term stability
- Move to EKF after baseline validation
- Use timestamps on every frame and IMU sample

## 6. Real-Time AR Overlay Progression
### Phase 1 overlay
- One world-space recipe card
- One active hint (arrow or highlight)
- Manual next-step button

### Phase 2 overlay
- Per-step object attachment
- Step confidence display
- Auto advance when verification passes

### Phase 3 overlay
- Multi-anchor placement (workspace card + local object hints)
- Occlusion aware rendering
- Smoother re-anchoring under camera motion

## 7. Precise Localization for Requests Like Keyboard Key N
To support key-level guidance:
1. Detect keyboard bounding region
2. Estimate keyboard plane pose
3. Compute homography to canonical key layout
4. Map requested key coordinates to world point
5. Place highlight/arrow at mapped target
6. Recompute per update and smooth motion

This is fully possible, but should be in a dedicated precision module after object-level overlay is stable.

## 8. Asset and Animation Strategy
### Asset sources
- Use curated static packs for kitchen props, ingredients, and utensils
- Keep generated assets optional for rapid concepting

### 404-GEN usage guidance
- Good for concept prototyping and quick asset ideation
- Use generated content as draft or filler assets
- Validate polycount, collider behavior, and visual consistency before production use

### Animation approach
- Use simple, reusable procedural cues first:
  - Arrow pulse
  - Outline glow
  - Path arc for motion direction
- For object actions like chopping:
  - Animator clips on guide prefabs
  - Timeline sequences for step demos
  - Optional VFX Graph trails for tool motion

### Performance guidance
- Prefer lightweight shaders and pooled prefabs
- Keep one active primary hint and limited secondary hints
- Use LOD or simplified mesh versions where possible

## 9. Recommended Final Phases and Exit Criteria
## Phase A - Stabilize Hybrid Contracts
Deliverables:
- Canonical guidance JSON schema with step array and active hint
- Unity parser and error-safe handling

Exit criteria:
- Stable parse across snapshot and prompt flows with no UI stalls

## Phase B - YOLO26 Fast Layer
Deliverables:
- ONNX inference service
- Detection outputs integrated into scene fusion

Exit criteria:
- Real-time detections displayed and logged with confidence

## Phase C - Live AR Step Overlay
Deliverables:
- World-space step card
- Arrow/highlight on target object

Exit criteria:
- User can complete 3-step guided flow in AR

## Phase D - IMU Assisted Tracking
Deliverables:
- IMU stream integration
- Smoothing and pose stabilization

Exit criteria:
- Lower overlay jitter during device motion

## Phase E - Precision Guidance Module
Deliverables:
- Keyboard or small-part localization prototype
- Key-level highlighting demo

Exit criteria:
- Reliable placement on at least one fine-grained object category

## Phase F - Evaluation and Thesis Packaging
Deliverables:
- Latency and stability benchmarks
- User study metrics and qualitative feedback
- Final architecture report and demo video

Exit criteria:
- Defensible final report with measurable outcomes

## 10. Immediate Next 10 Days (Actionable)
1. Implement step_guidance schema end-to-end in backend and Unity
2. Add YOLO26 ONNX service and merge detections into response debug block
3. Build world-space step card prefab and active hint renderer
4. Add imu message schema and Unity-side sensor sender
5. Create one kitchen demo scenario with 4 to 6 guided steps
6. Define benchmark script for latency, jitter, and step completion

## 11. Final Document Pack To Prepare Before Next Phase
Keep these four docs updated together:
1. [FINAL_PROJECT_ROADMAP.md](FINAL_PROJECT_ROADMAP.md) - execution roadmap
2. [Implementation_plan_2.0.md](Implementation_plan_2.0.md) - architecture rationale
3. [AR_LIVE_GUIDANCE_PHASE1_PLAN.md](AR_LIVE_GUIDANCE_PHASE1_PLAN.md) - immediate implementation details
4. A new evaluation tracker file with measurable KPIs per phase

## 12. Key Risks and Mitigations
Risk: Vision model latency spikes
- Mitigation: fast detector first, trigger heavy calls only when needed

Risk: Overlay drift in motion
- Mitigation: anchor smoothing + IMU fusion + periodic re-localization

Risk: Asset style inconsistency
- Mitigation: define style guide and approved pack list early

Risk: Over-complex scope
- Mitigation: lock MVP success criteria per phase and defer optional features

## 13. Recommended Decision Now
Proceed with a dual-track implementation:
- Track 1: Product track for reliable live AR guidance with step overlays
- Track 2: Research track for precision localization and hybrid perception evaluation

This keeps momentum, preserves your working model path, and adds the stronger technical depth required for a high-quality final project.
