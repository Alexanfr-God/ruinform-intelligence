#![allow(unexpected_cfgs)]

use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint,
    entrypoint::ProgramResult,
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    sysvar::Sysvar,
};
use solana_system_interface::{instruction as system_instruction, program as system_program};

entrypoint!(process_instruction);

const MAGIC: &[u8; 8] = b"RUFSALE1";
const VERSION: u8 = 2;
const STATUS_LISTED: u8 = 1;
const STATUS_FUNDED: u8 = 2;
const STATUS_SHIPPED: u8 = 3;
const STATUS_RECEIPT_CONFIRMED: u8 = 4;
const STATUS_SETTLED: u8 = 5;
const STATUS_CANCELLED: u8 = 6;
const LISTING_TTL_SECONDS: i64 = 14 * 24 * 60 * 60;
const SHIP_TTL_SECONDS: i64 = 3 * 24 * 60 * 60;
const REVIEW_AFTER_SHIP_SECONDS: i64 = 21 * 24 * 60 * 60;
const RUINFORM_BPS: u64 = 500;
const BPS_DENOM: u64 = 10_000;
const STATE_LEN: usize = 208;

#[repr(u32)]
enum EscrowError {
    InvalidInstruction = 1,
    InvalidPda = 2,
    InvalidState = 3,
    Unauthorized = 4,
    InvalidStatus = 5,
    InvalidPrice = 6,
    Expired = 7,
    NotExpired = 8,
    InsufficientEscrow = 9,
    InvalidAccount = 10,
}

impl From<EscrowError> for ProgramError {
    fn from(value: EscrowError) -> Self { ProgramError::Custom(value as u32) }
}

#[derive(Clone, Copy)]
struct SaleState {
    bump: u8,
    status: u8,
    nonce: u64,
    price: u64,
    expires_at: i64,
    seller: Pubkey,
    buyer: Pubkey,
    asset: Pubkey,
    treasury: Pubkey,
    object_hash: [u8; 32],
}

impl SaleState {
    fn pack(&self, dst: &mut [u8]) -> ProgramResult {
        if dst.len() < STATE_LEN { return Err(EscrowError::InvalidState.into()); }
        dst.fill(0);
        dst[0..8].copy_from_slice(MAGIC);
        dst[8] = VERSION;
        dst[9] = self.bump;
        dst[10] = self.status;
        dst[16..24].copy_from_slice(&self.nonce.to_le_bytes());
        dst[24..32].copy_from_slice(&self.price.to_le_bytes());
        dst[32..40].copy_from_slice(&self.expires_at.to_le_bytes());
        dst[40..72].copy_from_slice(self.seller.as_ref());
        dst[72..104].copy_from_slice(self.buyer.as_ref());
        dst[104..136].copy_from_slice(self.asset.as_ref());
        dst[136..168].copy_from_slice(self.treasury.as_ref());
        dst[168..200].copy_from_slice(&self.object_hash);
        Ok(())
    }

    fn unpack(src: &[u8]) -> Result<Self, ProgramError> {
        if src.len() < STATE_LEN || &src[0..8] != MAGIC || src[8] != VERSION {
            return Err(EscrowError::InvalidState.into());
        }
        let mut object_hash = [0u8; 32]; object_hash.copy_from_slice(&src[168..200]);
        Ok(Self {
            bump: src[9], status: src[10],
            nonce: u64::from_le_bytes(src[16..24].try_into().unwrap()),
            price: u64::from_le_bytes(src[24..32].try_into().unwrap()),
            expires_at: i64::from_le_bytes(src[32..40].try_into().unwrap()),
            seller: Pubkey::new_from_array(src[40..72].try_into().unwrap()),
            buyer: Pubkey::new_from_array(src[72..104].try_into().unwrap()),
            asset: Pubkey::new_from_array(src[104..136].try_into().unwrap()),
            treasury: Pubkey::new_from_array(src[136..168].try_into().unwrap()),
            object_hash,
        })
    }
}

fn read_u64(data: &[u8], offset: usize) -> Result<u64, ProgramError> {
    data.get(offset..offset+8).ok_or(EscrowError::InvalidInstruction)?
        .try_into().map(u64::from_le_bytes).map_err(|_| ProgramError::from(EscrowError::InvalidInstruction))
}

pub fn process_instruction(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let tag = *data.first().ok_or(EscrowError::InvalidInstruction)?;
    match tag {
        0 => initialize(program_id, accounts, data),
        1 => fund(program_id, accounts),
        2 => mark_shipped(program_id, accounts),
        3 => confirm_receipt(program_id, accounts),
        4 => settle(program_id, accounts),
        5 => seller_refund(program_id, accounts),
        6 => buyer_timeout_refund(program_id, accounts),
        7 => seller_cancel_listing(program_id, accounts),
        _ => Err(EscrowError::InvalidInstruction.into()),
    }
}

fn initialize(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    if data.len() != 1 + 8 + 8 + 32 { return Err(EscrowError::InvalidInstruction.into()); }
    let nonce = read_u64(data, 1)?;
    let price = read_u64(data, 9)?;
    if price == 0 { return Err(EscrowError::InvalidPrice.into()); }
    let mut object_hash = [0u8; 32]; object_hash.copy_from_slice(&data[17..49]);
    let mut it = accounts.iter();
    let seller = next_account_info(&mut it)?;
    let state = next_account_info(&mut it)?;
    let asset = next_account_info(&mut it)?;
    let treasury = next_account_info(&mut it)?;
    let system_program = next_account_info(&mut it)?;
    if !seller.is_signer || !seller.is_writable || !state.is_writable { return Err(EscrowError::Unauthorized.into()); }
    if *system_program.key != system_program::id() { return Err(EscrowError::InvalidAccount.into()); }
    let nonce_bytes = nonce.to_le_bytes();
    let (expected, bump) = Pubkey::find_program_address(&[b"sale", asset.key.as_ref(), &nonce_bytes], program_id);
    if expected != *state.key { return Err(EscrowError::InvalidPda.into()); }
    let rent = Rent::get()?.minimum_balance(STATE_LEN);
    let ix = system_instruction::create_account(seller.key, state.key, rent, STATE_LEN as u64, program_id);
    invoke_signed(&ix, &[seller.clone(), state.clone(), system_program.clone()], &[&[b"sale", asset.key.as_ref(), &nonce_bytes, &[bump]]])?;
    let now = Clock::get()?.unix_timestamp;
    SaleState { bump, status: STATUS_LISTED, nonce, price, expires_at: now + LISTING_TTL_SECONDS, seller: *seller.key, buyer: Pubkey::default(), asset: *asset.key, treasury: *treasury.key, object_hash }.pack(&mut state.try_borrow_mut_data()?)
}

fn fund(program_id: &Pubkey, accounts: &[AccountInfo]) -> ProgramResult {
    let mut it = accounts.iter();
    let buyer = next_account_info(&mut it)?;
    let state = next_account_info(&mut it)?;
    let system_program = next_account_info(&mut it)?;
    if state.owner != program_id || !buyer.is_signer || !buyer.is_writable || !state.is_writable { return Err(EscrowError::Unauthorized.into()); }
    if *system_program.key != system_program::id() { return Err(EscrowError::InvalidAccount.into()); }
    let mut sale = SaleState::unpack(&state.try_borrow_data()?)?;
    if sale.status != STATUS_LISTED { return Err(EscrowError::InvalidStatus.into()); }
    if *buyer.key == sale.seller { return Err(EscrowError::InvalidAccount.into()); }
    let now = Clock::get()?.unix_timestamp;
    if now > sale.expires_at { return Err(EscrowError::Expired.into()); }
    let ix = system_instruction::transfer(buyer.key, state.key, sale.price);
    solana_program::program::invoke(&ix, &[buyer.clone(), state.clone(), system_program.clone()])?;
    sale.buyer = *buyer.key;
    sale.status = STATUS_FUNDED;
    sale.expires_at = now + SHIP_TTL_SECONDS;
    sale.pack(&mut state.try_borrow_mut_data()?)
}

fn mark_shipped(program_id: &Pubkey, accounts: &[AccountInfo]) -> ProgramResult {
    let mut it = accounts.iter();
    let seller = next_account_info(&mut it)?;
    let state = next_account_info(&mut it)?;
    if state.owner != program_id || !seller.is_signer || !state.is_writable { return Err(EscrowError::Unauthorized.into()); }
    let mut sale = SaleState::unpack(&state.try_borrow_data()?)?;
    if *seller.key != sale.seller || sale.status != STATUS_FUNDED { return Err(EscrowError::InvalidStatus.into()); }
    let now = Clock::get()?.unix_timestamp;
    if now > sale.expires_at { return Err(EscrowError::Expired.into()); }
    sale.status = STATUS_SHIPPED;
    sale.expires_at = now + REVIEW_AFTER_SHIP_SECONDS;
    sale.pack(&mut state.try_borrow_mut_data()?)
}

fn confirm_receipt(program_id: &Pubkey, accounts: &[AccountInfo]) -> ProgramResult {
    let mut it = accounts.iter();
    let buyer = next_account_info(&mut it)?;
    let state = next_account_info(&mut it)?;
    if state.owner != program_id || !buyer.is_signer || !state.is_writable { return Err(EscrowError::Unauthorized.into()); }
    let mut sale = SaleState::unpack(&state.try_borrow_data()?)?;
    if *buyer.key != sale.buyer || sale.status != STATUS_SHIPPED { return Err(EscrowError::InvalidStatus.into()); }
    sale.status = STATUS_RECEIPT_CONFIRMED;
    sale.pack(&mut state.try_borrow_mut_data()?)
}

fn settle(program_id: &Pubkey, accounts: &[AccountInfo]) -> ProgramResult {
    let mut it = accounts.iter();
    let seller = next_account_info(&mut it)?;
    let state = next_account_info(&mut it)?;
    let treasury = next_account_info(&mut it)?;
    if state.owner != program_id || !seller.is_signer || !seller.is_writable || !state.is_writable || !treasury.is_writable { return Err(EscrowError::Unauthorized.into()); }
    let mut sale = SaleState::unpack(&state.try_borrow_data()?)?;
    if sale.status != STATUS_RECEIPT_CONFIRMED { return Err(EscrowError::InvalidStatus.into()); }
    if *seller.key != sale.seller || *treasury.key != sale.treasury { return Err(EscrowError::Unauthorized.into()); }
    if state.lamports() < sale.price { return Err(EscrowError::InsufficientEscrow.into()); }
    let fee = sale.price.checked_mul(RUINFORM_BPS).ok_or(EscrowError::InvalidPrice)?.checked_div(BPS_DENOM).ok_or(EscrowError::InvalidPrice)?;
    let seller_amount = sale.price.checked_sub(fee).ok_or(EscrowError::InvalidPrice)?;
    **state.try_borrow_mut_lamports()? = state.lamports().checked_sub(sale.price).ok_or(EscrowError::InsufficientEscrow)?;
    **seller.try_borrow_mut_lamports()? = seller.lamports().checked_add(seller_amount).ok_or(EscrowError::InvalidPrice)?;
    **treasury.try_borrow_mut_lamports()? = treasury.lamports().checked_add(fee).ok_or(EscrowError::InvalidPrice)?;
    sale.status = STATUS_SETTLED;
    sale.pack(&mut state.try_borrow_mut_data()?)
}

fn refund_to_buyer(state: &AccountInfo, buyer: &AccountInfo, sale: &mut SaleState) -> ProgramResult {
    if !state.is_writable || !buyer.is_writable || *buyer.key != sale.buyer { return Err(EscrowError::InvalidAccount.into()); }
    if state.lamports() < sale.price { return Err(EscrowError::InsufficientEscrow.into()); }
    **state.try_borrow_mut_lamports()? = state.lamports().checked_sub(sale.price).ok_or(EscrowError::InsufficientEscrow)?;
    **buyer.try_borrow_mut_lamports()? = buyer.lamports().checked_add(sale.price).ok_or(EscrowError::InvalidPrice)?;
    sale.status = STATUS_CANCELLED;
    sale.pack(&mut state.try_borrow_mut_data()?)
}

fn seller_refund(program_id: &Pubkey, accounts: &[AccountInfo]) -> ProgramResult {
    let mut it = accounts.iter();
    let seller = next_account_info(&mut it)?;
    let state = next_account_info(&mut it)?;
    let buyer = next_account_info(&mut it)?;
    if state.owner != program_id || !seller.is_signer { return Err(EscrowError::Unauthorized.into()); }
    let mut sale = SaleState::unpack(&state.try_borrow_data()?)?;
    if *seller.key != sale.seller || !matches!(sale.status, STATUS_FUNDED | STATUS_SHIPPED) { return Err(EscrowError::InvalidStatus.into()); }
    refund_to_buyer(state, buyer, &mut sale)
}

fn buyer_timeout_refund(program_id: &Pubkey, accounts: &[AccountInfo]) -> ProgramResult {
    let mut it = accounts.iter();
    let buyer = next_account_info(&mut it)?;
    let state = next_account_info(&mut it)?;
    if state.owner != program_id || !buyer.is_signer { return Err(EscrowError::Unauthorized.into()); }
    let mut sale = SaleState::unpack(&state.try_borrow_data()?)?;
    if *buyer.key != sale.buyer || sale.status != STATUS_FUNDED { return Err(EscrowError::InvalidStatus.into()); }
    if Clock::get()?.unix_timestamp <= sale.expires_at { return Err(EscrowError::NotExpired.into()); }
    refund_to_buyer(state, buyer, &mut sale)
}

fn seller_cancel_listing(program_id: &Pubkey, accounts: &[AccountInfo]) -> ProgramResult {
    let mut it = accounts.iter();
    let seller = next_account_info(&mut it)?;
    let state = next_account_info(&mut it)?;
    if state.owner != program_id || !seller.is_signer || !state.is_writable { return Err(EscrowError::Unauthorized.into()); }
    let mut sale = SaleState::unpack(&state.try_borrow_data()?)?;
    if *seller.key != sale.seller || sale.status != STATUS_LISTED { return Err(EscrowError::InvalidStatus.into()); }
    sale.status = STATUS_CANCELLED;
    sale.pack(&mut state.try_borrow_mut_data()?)
}
