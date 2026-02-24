/* Enhanced UI engine: sidebar toggle + ripple + navbar scroll */
(function(){
  // Ripple & keyboard accessible
  function triggerRipple(e){
    const target = (e.target && e.target.closest(".btn, .side-link, button")) || e.target;
    if(!target) return;
    if(window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const existing = target.querySelector(".ripple");
    if(existing) existing.remove();
    const rect = target.getBoundingClientRect();
    const circle = document.createElement("span");
    circle.className = "ripple";
    const size = Math.max(rect.width, rect.height)*2;
    circle.style.width = circle.style.height = size + "px";
    const cx = e.clientX || (rect.left + rect.width/2);
    const cy = e.clientY || (rect.top + rect.height/2);
    circle.style.left = (cx - rect.left - size/2) + "px";
    circle.style.top = (cy - rect.top - size/2) + "px";
    target.appendChild(circle);
    circle.addEventListener("animationend", ()=>{ circle.remove(); });
  }

  document.addEventListener("click", triggerRipple);
  document.addEventListener("keydown", (e)=>{
    if(e.key==="Enter"||e.key===" "){
      const t = document.activeElement;
      if(t && (t.matches(".btn")||t.matches(".side-link")||t.tagName==="BUTTON")){
        e.preventDefault();
        triggerRipple({target:t, clientX: t.getBoundingClientRect().left + t.getBoundingClientRect().width/2, clientY: t.getBoundingClientRect().top + t.getBoundingClientRect().height/2});
      }
    }
  });

  // Navbar scroll
  (()=>{
    const nav = document.querySelector(".glass-nav");
    if(!nav) return;
    let last = 0;
    window.addEventListener("scroll", ()=> {
      last = window.scrollY;
      window.requestAnimationFrame(()=> nav.classList.toggle("scrolled", last>10));
    }, {passive:true});
  })();

  // Sidebar toggle
  const sidebar = document.getElementById("sidebar");
  const content = document.getElementById("contentArea");
  const toggle = document.getElementById("sidebarToggle");
  if(toggle && sidebar && content){
    toggle.addEventListener("click", ()=>{
      sidebar.classList.toggle("show");
      content.classList.toggle("shift");
    });
  }

})();
