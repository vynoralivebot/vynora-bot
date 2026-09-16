const tg = window.Telegram.WebApp;
tg.expand();

// Get Telegram User ID dynamically (with fallback for local testing)
const userId = tg.initDataUnsafe?.user?.id || 12345678;

async function fetchHosts() {
    try {
        const response = await fetch('/api/hosts');
        const data = await response.json();
        const hosts = data.hosts || [];
        const container = document.getElementById('hosts-container');
        
        if (!container) return;
        container.innerHTML = '';
        
        if (hosts.length === 0) {
            container.innerHTML = '<p style="text-align:center; color:#888; padding: 20px;">No online hosts available right now.</p>';
            return;
        }

        hosts.forEach(host => {
            const rate = host.rate || 10; // Default tokens per min
            const cost1 = rate * 1;
            const cost5 = rate * 5;
            const cost10 = rate * 10;

            container.innerHTML += `
                <div class="host-card" style="background: #1e1e1e; padding: 15px; border-radius: 12px; margin-bottom: 12px; display: flex; gap: 15px; align-items: center; border: 1px solid #333;">
                    <img src="${host.img || 'https://via.placeholder.com/70'}" alt="Host" style="width: 70px; height: 70px; border-radius: 50%; object-fit: cover;">
                    <div style="flex: 1;">
                        <h3 style="margin: 0 0 4px 0; color: #fff; font-size: 16px;">${host.name} <span style="font-size: 11px; color: #2ecc71; background: rgba(46,204,113,0.1); padding: 2px 6px; border-radius: 4px;">● Online</span></h3>
                        <p style="margin: 0 0 10px 0; font-size: 12px; color: #bbb;">Rate: 🪙 ${rate} Tokens/min | 🌍 ${host.lang || 'English'}</p>
                        <div class="pricing-tiers" style="display: flex; gap: 6px;">
                            <button onclick="bookHost('${host.id || host.user_id}', '${host.name}', 1, ${cost1})" style="padding: 6px 10px; background: #0088cc; color: #fff; border: none; border-radius: 6px; font-size: 11px; cursor: pointer; font-weight: bold;">1m (${cost1} T)</button>
                            <button onclick="bookHost('${host.id || host.user_id}', '${host.name}', 5, ${cost5})" style="padding: 6px 10px; background: #0088cc; color: #fff; border: none; border-radius: 6px; font-size: 11px; cursor: pointer; font-weight: bold;">5m (${cost5} T)</button>
                            <button onclick="bookHost('${host.id || host.user_id}', '${host.name}', 10, ${cost10})" style="padding: 6px 10px; background: #0088cc; color: #fff; border: none; border-radius: 6px; font-size: 11px; cursor: pointer; font-weight: bold;">10m (${cost10} T)</button>
                        </div>
                    </div>
                </div>
            `;
        });
    } catch (error) {
        console.error("Error fetching hosts:", error);
    }
}

async function bookHost(hostId, hostName, duration, tokenCost) {
    if (!confirm(`Confirm booking with ${hostName} for ${duration} minutes at the cost of ${tokenCost} tokens?`)) {
        return;
    }

    try {
        const response = await fetch('/api/book-slot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                host_id: hostId,
                host_name: hostName,
                duration_mins: duration,
                token_cost: tokenCost
            })
        });

        const result = await response.json();
        if (result.status === 'success') {
            alert('✅ Booking request sent successfully! Waiting for the host to accept.');
        } else {
            alert('❌ ' + (result.message || 'Failed to book slot.'));
        }
    } catch (error) {
        console.error("Booking error:", error);
        alert('❌ An error occurred while booking the slot.');
    }
}

// Initial fetch on load
fetchHosts();

function openGiftModal(hostId) {
    const modal = document.getElementById('gift-modal-id'); 
    if (modal) {
        modal.style.display = 'block'; 
    }
}
